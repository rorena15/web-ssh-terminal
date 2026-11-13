"""명세 v1.2 (2026-11-13) 검증 시험: W.S.T 자동 업데이트 (증분·서명).
실행: python dev/harness/t_update.py [저장소_루트]"""
import base64
import contextlib
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# 요구 (7): 저장소 루트는 sys.argv[1] 또는 이 파일 기준 parents[2]
ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# 모든 파일 작업은 tempfile 폴더 안에서 수행
TEST_TMP_ROOT = Path(tempfile.mkdtemp(prefix="wst_t_update_"))
os.environ["WEBSSH_DATA"] = str(TEST_TMP_ROOT / "default_data")
os.environ["WST_UPDATE_DIR"] = str(TEST_TMP_ROOT / "default_upd")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from wst import update

# 가정: common 모듈은 wst.common 또는 최상위 common으로 임포트될 수 있으므로 둘 다 탐색하여 FROZEN 플래그를 제어한다.
common_mod = None
for _mod_name in ("wst.common", "common"):
    try:
        common_mod = __import__(_mod_name, fromlist=["FROZEN"])
        break
    except Exception:
        pass

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def expect_update_error(name, fn, detail=""):
    try:
        fn()
    except update.UpdateError as exc:
        check(name, True, detail or str(exc))
    except Exception as exc:
        check(name, False, f"UpdateError 대신 {type(exc).__name__} 발생: {exc}")
    else:
        check(name, False, "UpdateError가 발생하지 않고 통과함")


def make_keypair():
    """요구 (3): Ed25519 키쌍 생성 및 base64 인코딩."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_b64 = base64.b64encode(priv.private_bytes_raw()).decode("ascii")
    pub_b64 = base64.b64encode(pub.public_bytes_raw()).decode("ascii")
    return priv, priv_b64, pub_b64


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_release_bundle(
    priv_key: Ed25519PrivateKey,
    files_map: dict[str, bytes],
    version: str = "1.2.0",
    build_no: int = 7,
    fmt: int = 1,
    compress_type: int = zipfile.ZIP_DEFLATED,
    notes_url: str = "https://github.com/rorena15/web-ssh-terminal/releases/tag/v1.2.0",
    override_manifest_fn=None,
    with_version_file: bool = True,
) -> tuple[bytes, bytes, bytes, dict]:
    """요구 (4): zipfile로 W.S.T/ 접두 zip을 생성하고 로컬 헤더를 직접 읽어 data_offset을 계산한 뒤 서명."""
    # Claude 수정: 새 버전 릴리즈에도 실제처럼 _internal/version_info.txt 포함
    if with_version_file and "_internal/version_info.txt" not in files_map and "W.S.T.exe" in files_map:
        files_map = {**files_map, "_internal/version_info.txt": f"StringStruct('FileVersion', '{version}'),\n".encode()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compress_type) as zf:
        for rel_path, content in files_map.items():
            arcname = f"W.S.T/{rel_path}"
            zinfo = zipfile.ZipInfo(arcname)
            zinfo.compress_type = compress_type
            zf.writestr(zinfo, content)
    zip_bytes = buf.getvalue()

    manifest_files = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for zinfo in zf.infolist():
            assert zinfo.filename.startswith("W.S.T/")
            rel_path = zinfo.filename[len("W.S.T/"):]
            hdr_ofs = zinfo.header_offset
            # 명세 1절: 로컬 헤더 30바이트 + 파일 이름 길이 + extra 길이 뒤가 data_offset
            sig, _ver, _flags, method, _time, _date, _crc, comp_sz, uncomp_sz, fname_len, extra_len = (
                struct.unpack("<4s5H3I2H", zip_bytes[hdr_ofs : hdr_ofs + 30])
            )
            assert sig == b"PK\x03\x04", f"잘못된 로컬 헤더 시그니처: {sig!r}"
            data_offset = hdr_ofs + 30 + fname_len + extra_len
            raw_content = files_map[rel_path]
            manifest_files.append(
                {
                    "path": rel_path,
                    "size": len(raw_content),
                    "sha256": sha256_hex(raw_content),
                    "data_offset": data_offset,
                    "compress_size": comp_sz,
                    "method": method,
                }
            )

    manifest_obj = {
        "format": fmt,
        "version": version,
        "build": build_no,
        "published": "2026-11-20T00:00:00Z",
        "zip": {
            "name": f"W.S.T-v{version}-win64.zip",
            "size": len(zip_bytes),
            "sha256": sha256_hex(zip_bytes),
        },
        "files": manifest_files,
        "notes_url": notes_url,
    }
    if override_manifest_fn is not None:
        override_manifest_fn(manifest_obj)

    manifest_bytes = json.dumps(manifest_obj, ensure_ascii=False, indent=2).encode("utf-8")
    sig_bytes = priv_key.sign(manifest_bytes)
    return zip_bytes, manifest_bytes, sig_bytes, manifest_obj


class LocalUpdateServer:
    """요구 (5): Range 지원/미지원을 선택할 수 있는 스레드 기반 로컬 http.server 및 요청 로그 기록."""

    def __init__(self, support_range: bool = True, corrupt_zip: bool = False):
        self.support_range = support_range
        self.corrupt_zip = corrupt_zip
        self.requests_log: list[dict] = []
        self.routes: dict[str, bytes] = {}
        self._lock = threading.Lock()

        parent = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                range_hdr = self.headers.get("Range")
                ua_hdr = self.headers.get("User-Agent", "")
                with parent._lock:
                    parent.requests_log.append(
                        {
                            "method": "GET",
                            "path": path,
                            "range": range_hdr,
                            "user_agent": ua_hdr,
                            "headers": dict(self.headers.items()),
                        }
                    )

                if path not in parent.routes:
                    self.send_response(404)
                    self.end_headers()
                    return

                data = parent.routes[path]
                if parent.corrupt_zip and path.endswith(".zip"):
                    # 해시 불일치 유발을 위해 모든 바이트 반전
                    data = bytes(b ^ 0xFF for b in data)

                if parent.support_range and range_hdr and range_hdr.startswith("bytes="):
                    m = re.match(r"^bytes=(\d+)-(\d+)$", range_hdr.strip())
                    if m:
                        start = int(m.group(1))
                        end = int(m.group(2))
                        if 0 <= start <= end < len(data):
                            chunk = data[start : end + 1]
                            self.send_response(206)
                            self.send_header("Content-Type", "application/octet-stream")
                            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                            self.send_header("Content-Length", str(len(chunk)))
                            self.end_headers()
                            self.wfile.write(chunk)
                            return

                self.send_response(200)
                ctype = "application/json" if path.endswith(".json") or path.endswith("/latest") else "application/octet-stream"
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        # 가정: 명세 3절 'HTTPS만' 검사를 통과하면서도 로컬 http.server로 연결되도록 https://127.0.0.1 URL과 전용 opener를 함께 제공한다.
        return f"https://127.0.0.1:{self.port}"

    def make_opener(self) -> urllib.request.OpenerDirector:
        """https://127.0.0.1 요청을 로컬 평문 HTTP 서버로 전달하는 시험용 opener."""

        class LocalLoopbackHandler(urllib.request.HTTPHandler):
            handler_order = 100  # Claude 수정: 기본 HTTPSHandler(500)보다 먼저 https 요청을 가로챔
            def https_open(self, req):
                return self.http_open(req)

            def https_request(self, req):
                return self.http_request(req)

        return urllib.request.build_opener(LocalLoopbackHandler())

    def set_release(self, zip_name: str, zip_bytes: bytes, manifest_bytes: bytes, sig_bytes: bytes, tag: str = "v1.2.0"):
        zip_path = f"/download/{zip_name}"
        manifest_path = "/download/manifest.json"
        sig_path = "/download/manifest.json.sig"
        self.routes[zip_path] = zip_bytes
        self.routes[manifest_path] = manifest_bytes
        self.routes[sig_path] = sig_bytes

        latest_payload = {
            "tag_name": tag,
            "name": tag,
            "assets": [
                {"name": zip_name, "browser_download_url": f"{self.base_url}{zip_path}", "size": len(zip_bytes)},
                {"name": "manifest.json", "browser_download_url": f"{self.base_url}{manifest_path}", "size": len(manifest_bytes)},
                {"name": "manifest.json.sig", "browser_download_url": f"{self.base_url}{sig_path}", "size": len(sig_bytes)},
            ],
        }
        self.routes["/repos/rorena15/web-ssh-terminal/releases/latest"] = json.dumps(latest_payload).encode("utf-8")
        return {
            "zip_url": f"{self.base_url}{zip_path}",
            "manifest_url": f"{self.base_url}{manifest_path}",
            "sig_url": f"{self.base_url}{sig_path}",
            "latest_url": f"{self.base_url}/repos/rorena15/web-ssh-terminal/releases/latest",
        }

    def clear_log(self):
        with self._lock:
            self.requests_log.clear()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def write_version_info(base_dir: Path, ver: str = "1.1.0"):
    """가정: apply_update 또는 버전 조회 함수가 target의 version_info.txt에서 FileVersion을 읽을 수 있으므로 표준 PyInstaller 버전 파일 형식을 배치."""
    parts = ver.split(".")
    nums = ", ".join(parts + ["0"])
    content = (
        f"VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums})),\n"
        f"  kids=[StringFileInfo([StringTable('040904B0', [\n"
        f"    StringStruct('FileVersion', '{ver}'),\n"
        f"    StringStruct('ProductVersion', '{ver}')])])]\n"
        f")\n"
    )
    # Claude 수정: 실제 배포본 위치(_internal/version_info.txt)에 둔다
    (base_dir / "_internal").mkdir(parents=True, exist_ok=True)
    (base_dir / "_internal" / "version_info.txt").write_text(content, encoding="utf-8")


def setup_fake_installation(base_dir: Path, files_map: dict[str, bytes], current_version: str = "1.1.0"):
    """임시 BASE 폴더에 관리 대상 및 비관리 대상(data/, logs/, certs/, 사용자 파일, 실행.vbs) 배치."""
    base_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files_map.items():
        p = base_dir / Path(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    write_version_info(base_dir, current_version)

    # 명세 0절 & 8절: 절대 건드리면 안 되는 비관리 항목들
    (base_dir / "data").mkdir(exist_ok=True)
    (base_dir / "data" / "user_db.json").write_text('{"hosts": ["10.0.0.1"]}', encoding="utf-8")
    (base_dir / "logs").mkdir(exist_ok=True)
    (base_dir / "logs" / "app.log").write_text("log line 1\n", encoding="utf-8")
    (base_dir / "certs").mkdir(exist_ok=True)
    (base_dir / "certs" / "localhost.pem").write_text("-----BEGIN CERT-----", encoding="utf-8")
    (base_dir / "사용자메모.txt").write_text("개인 메모 파일", encoding="utf-8")
    (base_dir / "실행.vbs").write_text('CreateObject("WScript.Shell").Run "W.S.T.exe"', encoding="utf-8")


@contextlib.contextmanager
def set_frozen(val: bool):
    """common.FROZEN 및 update.FROZEN(있을 경우)을 일시 변경."""
    sentinel = object()
    old_common = getattr(common_mod, "FROZEN", sentinel) if common_mod else sentinel
    old_update = getattr(update, "FROZEN", sentinel)
    try:
        if common_mod is not None:
            setattr(common_mod, "FROZEN", val)
        if hasattr(update, "FROZEN") or common_mod is None:
            setattr(update, "FROZEN", val)
        yield
    finally:
        if common_mod is not None:
            if old_common is sentinel:
                delattr(common_mod, "FROZEN")
            else:
                setattr(common_mod, "FROZEN", old_common)
        if old_update is sentinel:
            if hasattr(update, "FROZEN"):
                delattr(update, "FROZEN")
        else:
            setattr(update, "FROZEN", old_update)


def run_tests():
    priv_key, _priv_b64, pub_b64 = make_keypair()
    other_priv_key, _, _ = make_keypair()

    # =========================================================================
    # 1. 명세 2절 & 6.5절: 버전 파싱, 서명, 버전 비교, 경로 규칙, 크기/오프셋 검증
    # =========================================================================

    # [명세 6.5절] parse_version 정상 동작 및 형식 오류 거부
    try:
        v_parsed = update.parse_version("1.2.0")
        check("parse_version 정상('1.2.0' -> (1, 2, 0))", v_parsed == (1, 2, 0), f"결과={v_parsed}")
    except Exception as exc:
        check("parse_version 정상('1.2.0' -> (1, 2, 0))", False, str(exc))

    for bad_ver in ("1.2", "1.2.0.0", "v1.2.0", "1.2.a", "1.-1.0", ""):
        expect_update_error(
            f"parse_version 형식 오류 거부({bad_ver!r})",
            lambda bv=bad_ver: update.parse_version(bv),
        )

    base_v12_files = {
        "W.S.T.exe": b"MZ-fake-exe-v1.2.0-" + (b"A" * 4096),
        "_internal/core.pyd": b"pyd-v1.2.0-binary",
        "static/app.js": b"console.log('v1.2.0');",
        "LICENSE": b"MIT License",
        "README.md": b"# W.S.T",
        "README.ko.md": "# W.S.T 한국어".encode("utf-8"),
        "SECURITY.md": b"# Security",
    }
    zip_bytes, manifest_bytes, sig_bytes, _ = build_release_bundle(priv_key, base_v12_files, version="1.2.0")

    # [명세 2절 규칙 1~5, 8절] 올바른 서명 통과
    try:
        parsed_m = update.verify_manifest(manifest_bytes, sig_bytes, "1.1.0", pubkey_b64=pub_b64)
        check(
            "verify_manifest 올바른 서명·매니페스트 통과",
            isinstance(parsed_m, dict) and parsed_m.get("version") == "1.2.0",
        )
    except Exception as exc:
        check("verify_manifest 올바른 서명·매니페스트 통과", False, str(exc))

    # [명세 2절 규칙 1, 8절] 1바이트 변조된 manifest 거부
    tampered_manifest = bytearray(manifest_bytes)
    tampered_manifest[len(tampered_manifest) // 2] ^= 0x01
    expect_update_error(
        "verify_manifest 1바이트 변조된 manifest 거부",
        lambda: update.verify_manifest(bytes(tampered_manifest), sig_bytes, "1.1.0", pubkey_b64=pub_b64),
    )

    # [명세 2절 규칙 1, 8절] 1바이트 변조된 sig 거부
    tampered_sig = bytearray(sig_bytes)
    tampered_sig[0] ^= 0x01
    expect_update_error(
        "verify_manifest 1바이트 변조된 sig 거부",
        lambda: update.verify_manifest(manifest_bytes, bytes(tampered_sig), "1.1.0", pubkey_b64=pub_b64),
    )

    # [명세 2절 규칙 1, 8절] 다른 키 서명 거부
    other_sig = other_priv_key.sign(manifest_bytes)
    expect_update_error(
        "verify_manifest 다른 키로 서명된 sig 거부",
        lambda: update.verify_manifest(manifest_bytes, other_sig, "1.1.0", pubkey_b64=pub_b64),
    )

    # [명세 2절 규칙 2] format != 1 거부
    _, bad_fmt_m, bad_fmt_s, _ = build_release_bundle(priv_key, base_v12_files, version="1.2.0", fmt=2)
    expect_update_error(
        "verify_manifest format != 1 거부",
        lambda: update.verify_manifest(bad_fmt_m, bad_fmt_s, "1.1.0", pubkey_b64=pub_b64),
    )

    # [명세 2절 규칙 3, 8절] 같은 버전 거부
    expect_update_error(
        "verify_manifest 같은 버전(1.2.0 vs 1.2.0) 거부",
        lambda: update.verify_manifest(manifest_bytes, sig_bytes, "1.2.0", pubkey_b64=pub_b64),
    )

    # [명세 2절 규칙 3, 8절] 낮은 버전(다운그레이드) 거부
    expect_update_error(
        "verify_manifest 낮은 버전(1.2.0 vs 현재 1.3.0) 거부",
        lambda: update.verify_manifest(manifest_bytes, sig_bytes, "1.3.0", pubkey_b64=pub_b64),
    )

    # [명세 2절 규칙 4, 6.5절 check_path, 8절] 경로 규칙 위반 각각 거부
    invalid_paths = [
        ("빈 경로", ""),
        ("상위 경로(..)", "static/../W.S.T.exe"),
        ("현재 경로(.)", "static/./app.js"),
        ("빈 구성 요소(//)", "static//app.js"),
        ("절대 경로(/)", "/W.S.T.exe"),
        ("드라이브 콜론(C:)", "C:W.S.T.exe"),
        ("경로 내 콜론(:)", "static/bad:name.js"),
        ("백슬래시(\\)", "static\\app.js"),
        ("NUL 문자", "static/app\x00.js"),
        ("예약 이름 con.txt", "static/con.txt"),
        ("예약 이름 Aux", "static/Aux"),
        ("예약 이름 COM1.log", "_internal/COM1.log"),
        ("예약 이름 lpt9", "_internal/lpt9"),
        ("끝 점(file.)", "static/app.js."),
        ("끝 공백(file )", "static/app.js "),
        ("관리 대상 밖(data/x)", "data/x"),
        ("관리 대상 밖(logs/a.log)", "logs/a.log"),
        ("관리 대상 밖(실행.vbs)", "실행.vbs"),
    ]
    for label, bad_p in invalid_paths:
        expect_update_error(
            f"check_path 경로 위반 거부: {label}",
            lambda bp=bad_p: update.check_path(bp),
        )
        # verify_manifest에서도 거부되는지 함께 확인
        def _inject_bad_path(m_obj, bp=bad_p):
            m_obj["files"].append(
                {"path": bp, "size": 1, "sha256": "0" * 64, "data_offset": 0, "compress_size": 1, "method": 8}
            )

        _, bm_bytes, bs_bytes, _ = build_release_bundle(
            priv_key, base_v12_files, version="1.2.0", override_manifest_fn=_inject_bad_path
        )
        expect_update_error(
            f"verify_manifest 경로 위반 거부: {label}",
            lambda bmb=bm_bytes, bsb=bs_bytes: update.verify_manifest(bmb, bsb, "1.1.0", pubkey_b64=pub_b64),
        )

    # [명세 2절 규칙 4, 8절] 대소문자 무시 중복 경로 거부
    def _inject_case_dup(m_obj):
        m_obj["files"].append(
            {
                "path": "STATIC/APP.JS",
                "size": 10,
                "sha256": "a" * 64,
                "data_offset": 0,
                "compress_size": 10,
                "method": 8,
            }
        )

    _, dup_m, dup_s, _ = build_release_bundle(
        priv_key, base_v12_files, version="1.2.0", override_manifest_fn=_inject_case_dup
    )
    expect_update_error(
        "verify_manifest 대소문자 무시 중복 경로 거부",
        lambda: update.verify_manifest(dup_m, dup_s, "1.1.0", pubkey_b64=pub_b64),
    )

    # [명세 2절 규칙 4, 8절] W.S.T.exe 누락 거부
    no_exe_files = {"static/app.js": b"console.log(1);"}
    _, noexe_m, noexe_s, _ = build_release_bundle(priv_key, no_exe_files, version="1.2.0")
    expect_update_error(
        "verify_manifest W.S.T.exe 누락 거부",
        lambda: update.verify_manifest(noexe_m, noexe_s, "1.1.0", pubkey_b64=pub_b64),
    )

    # [명세 1절, 2절 규칙 5, 8절] 크기·오프셋·압축방식 범위 위반 거부
    range_violation_cases = [
        ("음수 size", lambda m: m["files"][0].update({"size": -1})),
        ("음수 compress_size", lambda m: m["files"][0].update({"compress_size": -1})),
        ("음수 data_offset", lambda m: m["files"][0].update({"data_offset": -1})),
        (
            "data_offset + compress_size > zip.size",
            lambda m: m["files"][0].update({"data_offset": m["zip"]["size"], "compress_size": 10}),
        ),
        ("파일 합계 크기 > 1GB", lambda m: m["files"][0].update({"size": (1024 ** 3) + 1})),
        ("허용되지 않은 method(99)", lambda m: m["files"][0].update({"method": 99})),
    ]
    for label, mutator in range_violation_cases:
        _, bad_m, bad_s, _ = build_release_bundle(
            priv_key, base_v12_files, version="1.2.0", override_manifest_fn=mutator
        )
        expect_update_error(
            f"verify_manifest 범위/규칙 위반 거부: {label}",
            lambda bm=bad_m, bs=bad_s: update.verify_manifest(bm, bs, "1.1.0", pubkey_b64=pub_b64),
        )

    # =========================================================================
    # 2. 명세 3절 & 6.5절: local_hashes, plan, prepare (Range 증분, 200 폴백, 50% 초과, 해시 불일치)
    # =========================================================================

    # 증분 테스트용: 변경되지 않는 W.S.T.exe는 압축 크기가 충분히 크도록 의사 난수 바이트(약 40KB)로 생성,
    # 변경되는 static/app.js는 작게(수십 바이트) 만들어 변경분 압축 크기가 전체 zip의 50% 미만(~1%)이 되도록 구성.
    unchanged_exe_bytes = hashlib.pbkdf2_hmac("sha256", b"wst-exe-seed", b"salt", 1, dklen=40000)
    unchanged_pyd_bytes = hashlib.pbkdf2_hmac("sha256", b"wst-pyd-seed", b"salt", 1, dklen=10000)

    v11_files = {
        "W.S.T.exe": unchanged_exe_bytes,
        "_internal/core.pyd": unchanged_pyd_bytes,
        "_internal/obsolete.pyd": b"old-pyd-to-be-removed",
        "static/app.js": b"console.log('old v1.1.0');",
        "LICENSE": b"MIT License",
    }
    v12_incremental_files = {
        "W.S.T.exe": unchanged_exe_bytes,
        "_internal/core.pyd": unchanged_pyd_bytes,
        "static/app.js": b"console.log('new v1.2.0 updated!');",
        "static/new_feature.js": b"export const feature = true;",
        "LICENSE": b"MIT License",
    }

    inc_zip, inc_m_bytes, inc_sig, inc_m_obj = build_release_bundle(
        priv_key, v12_incremental_files, version="1.2.0"
    )

    base_inc = TEST_TMP_ROOT / "base_inc"
    upd_inc = TEST_TMP_ROOT / "upd_inc"
    setup_fake_installation(base_inc, v11_files, current_version="1.1.0")

    # [명세 3절, 6.5절] local_hashes 및 plan 검증
    try:
        lh = update.local_hashes(base_inc)
        has_managed = "W.S.T.exe" in lh and "static/app.js" in lh and "_internal/obsolete.pyd" in lh
        no_unmanaged = all(
            not k.startswith(("data/", "logs/", "certs/")) and k not in ("사용자메모.txt", "실행.vbs", "version_info.txt")
            for k in lh
        )
        check(
            "local_hashes 관리 대상만 정확히 해시 계산",
            has_managed and no_unmanaged and lh["W.S.T.exe"] == sha256_hex(unchanged_exe_bytes),
            f"keys={sorted(lh.keys())}",
        )
    except Exception as exc:
        check("local_hashes 관리 대상만 정확히 해시 계산", False, str(exc))

    try:
        to_download = update.plan(inc_m_obj, base_inc)
        planned_paths = sorted(item["path"] for item in to_download)
        check(
            "plan 변경·추가된 파일만 반환",
            planned_paths == ["_internal/version_info.txt", "static/app.js", "static/new_feature.js"],  # Claude 수정: 버전 파일도 바뀜
            f"planned={planned_paths}",
        )
    except Exception as exc:
        check("plan 변경·추가된 파일만 반환", False, str(exc))

    # [명세 3절, 8절] 로컬 HTTP 서버(Range 지원)로 증분 받기 — 바뀐 파일만 Range 요청했는지 로그 확인
    srv_range = LocalUpdateServer(support_range=True)
    try:
        urls = srv_range.set_release("W.S.T-v1.2.0-win64.zip", inc_zip, inc_m_bytes, inc_sig)
        opener = srv_range.make_opener()

        # 오래된 다른 버전 staging 미리 생성해 삭제 여부도 검증 (명세 3절: 오래된 다른 버전 staging은 삭제)
        old_staging = upd_inc / "staging" / "1.0.0"
        old_staging.mkdir(parents=True, exist_ok=True)
        (old_staging / "dummy.txt").write_text("old", encoding="utf-8")

        staging_path = update.prepare(
            inc_m_bytes,
            inc_sig,
            urls["zip_url"],
            base_inc,
            upd_inc,
            "1.1.0",
            pubkey_b64=pub_b64,
            opener=opener,
        )

        zip_reqs = [r for r in srv_range.requests_log if r["path"].endswith(".zip")]
        all_have_range = len(zip_reqs) >= 1 and all(r["range"] and r["range"].startswith("bytes=") for r in zip_reqs)

        # W.S.T.exe의 오프셋 구간이 요청되지 않았는지 확인
        exe_entry = next(f for f in inc_m_obj["files"] if f["path"] == "W.S.T.exe")
        exe_start = exe_entry["data_offset"]
        exe_end = exe_start + exe_entry["compress_size"] - 1
        requested_exe = False
        for r in zip_reqs:
            m = re.match(r"^bytes=(\d+)-(\d+)$", (r["range"] or "").strip())
            if m:
                rs, re_ = int(m.group(1)), int(m.group(2))
                if rs <= exe_start and re_ >= exe_end:
                    requested_exe = True

        staged_ok = (
            staging_path.exists()
            and (staging_path / "W.S.T.exe").read_bytes() == unchanged_exe_bytes
            and (staging_path / "static" / "app.js").read_bytes() == v12_incremental_files["static/app.js"]
            and (staging_path / "static" / "new_feature.js").read_bytes() == v12_incremental_files["static/new_feature.js"]
            and (staging_path / ".ready").exists()
        )
        check(
            "prepare(Range 지원) 바뀐 파일만 Range 요청 및 staging/.ready 생성",
            all_have_range and not requested_exe and staged_ok,
            f"zip_reqs={[r['range'] for r in zip_reqs]}, staged_ok={staged_ok}",
        )
        check(
            "prepare 오래된 다른 버전 staging 삭제",
            not old_staging.exists(),
        )

        # [명세 3절] 이미 같은 버전이 .ready면 다시 받지 않음
        srv_range.clear_log()
        staging_path_2 = update.prepare(
            inc_m_bytes,
            inc_sig,
            urls["zip_url"],
            base_inc,
            upd_inc,
            "1.1.0",
            pubkey_b64=pub_b64,
            opener=opener,
        )
        check(
            "prepare 이미 같은 버전이 .ready면 네트워크 재요청 없음",
            len(srv_range.requests_log) == 0 and staging_path_2 == staging_path,
            f"requests={len(srv_range.requests_log)}",
        )
    except Exception as exc:
        check("prepare(Range 지원) 바뀐 파일만 Range 요청 및 staging/.ready 생성", False, str(exc))
    finally:
        srv_range.close()

    # [명세 3절, 8절] Range 미지원(200 응답) → 전체 받기로 전환
    srv_norange = LocalUpdateServer(support_range=False)
    try:
        urls = srv_norange.set_release("W.S.T-v1.2.0-win64.zip", inc_zip, inc_m_bytes, inc_sig)
        opener = srv_norange.make_opener()
        upd_norange = TEST_TMP_ROOT / "upd_norange"
        staging_nr = update.prepare(
            inc_m_bytes,
            inc_sig,
            urls["zip_url"],
            base_inc,
            upd_norange,
            "1.1.0",
            pubkey_b64=pub_b64,
            opener=opener,
        )
        ok_nr = (
            staging_nr.exists()
            and (staging_nr / ".ready").exists()
            and (staging_nr / "static" / "app.js").read_bytes() == v12_incremental_files["static/app.js"]
            and (staging_nr / "W.S.T.exe").read_bytes() == unchanged_exe_bytes
        )
        check("prepare Range 미지원(200 응답) 시 전체 받기로 전환 성공", ok_nr)
    except Exception as exc:
        check("prepare Range 미지원(200 응답) 시 전체 받기로 전환 성공", False, str(exc))
    finally:
        srv_norange.close()

    # [명세 3절, 8절] 받을 압축 크기 합이 zip 크기의 50% 초과 → 전체 받기로 전환
    srv_over50 = LocalUpdateServer(support_range=True)
    try:
        # W.S.T.exe가 변경되어 받을 압축 크기가 전체 zip의 80% 이상을 차지하도록 설정
        new_big_exe = hashlib.pbkdf2_hmac("sha256", b"wst-exe-v1.2-new", b"salt", 1, dklen=40000)
        v12_over50_files = dict(v12_incremental_files, **{"W.S.T.exe": new_big_exe})
        z50, m50, s50, _ = build_release_bundle(priv_key, v12_over50_files, version="1.2.0")
        urls = srv_over50.set_release("W.S.T-v1.2.0-win64.zip", z50, m50, s50)
        opener = srv_over50.make_opener()
        upd_50 = TEST_TMP_ROOT / "upd_50"
        staging_50 = update.prepare(
            m50, s50, urls["zip_url"], base_inc, upd_50, "1.1.0", pubkey_b64=pub_b64, opener=opener
        )
        zip_reqs_50 = [r for r in srv_over50.requests_log if r["path"].endswith(".zip")]
        used_full_download = any(r["range"] is None for r in zip_reqs_50)
        check(
            "prepare 받을 압축 크기 > 50% 시 전체 받기(Range 없음) 전환",
            used_full_download and (staging_50 / "W.S.T.exe").read_bytes() == new_big_exe,
            f"zip_reqs={[r['range'] for r in zip_reqs_50]}",
        )
    except Exception as exc:
        check("prepare 받을 압축 크기 > 50% 시 전체 받기(Range 없음) 전환", False, str(exc))
    finally:
        srv_over50.close()

    # [명세 3절] 로컬에 W.S.T.exe가 없을 때 → 전체 받기로 전환
    srv_noexe = LocalUpdateServer(support_range=True)
    try:
        urls = srv_noexe.set_release("W.S.T-v1.2.0-win64.zip", inc_zip, inc_m_bytes, inc_sig)
        opener = srv_noexe.make_opener()
        base_missing_exe = TEST_TMP_ROOT / "base_missing_exe"
        files_without_exe = {k: v for k, v in v11_files.items() if k != "W.S.T.exe"}
        setup_fake_installation(base_missing_exe, files_without_exe, current_version="1.1.0")
        upd_missing_exe = TEST_TMP_ROOT / "upd_missing_exe"

        staging_me = update.prepare(
            inc_m_bytes,
            inc_sig,
            urls["zip_url"],
            base_missing_exe,
            upd_missing_exe,
            "1.1.0",
            pubkey_b64=pub_b64,
            opener=opener,
        )
        zip_reqs_me = [r for r in srv_noexe.requests_log if r["path"].endswith(".zip")]
        used_full_me = any(r["range"] is None for r in zip_reqs_me)
        check(
            "prepare 로컬 W.S.T.exe 없을 때 전체 받기 전환",
            used_full_me and (staging_me / "W.S.T.exe").read_bytes() == unchanged_exe_bytes,
            f"zip_reqs={[r['range'] for r in zip_reqs_me]}",
        )
    except Exception as exc:
        check("prepare 로컬 W.S.T.exe 없을 때 전체 받기 전환", False, str(exc))
    finally:
        srv_noexe.close()

    # [명세 3절, 8절] 받은 데이터 해시 불일치 → 포기·staging 삭제
    srv_corrupt = LocalUpdateServer(support_range=True, corrupt_zip=True)
    try:
        # method 0(저장)으로 압축해 변조 바이트가 압축 해제 에러가 아니라 SHA-256 해시 불일치로도 검증되게 함
        zc, mc, sc, _ = build_release_bundle(
            priv_key, v12_incremental_files, version="1.2.0", compress_type=zipfile.ZIP_STORED
        )
        urls = srv_corrupt.set_release("W.S.T-v1.2.0-win64.zip", zc, mc, sc)
        opener = srv_corrupt.make_opener()
        upd_corrupt = TEST_TMP_ROOT / "upd_corrupt"
        expect_update_error(
            "prepare 받은 데이터 해시 불일치 시 UpdateError 발생",
            lambda: update.prepare(
                mc, sc, urls["zip_url"], base_inc, upd_corrupt, "1.1.0", pubkey_b64=pub_b64, opener=opener
            ),
        )
        corrupt_staging_dir = upd_corrupt / "staging" / "1.2.0"
        check(
            "prepare 실패 시 해당 버전 staging 폴더 삭제됨",
            not corrupt_staging_dir.exists(),
        )
    finally:
        srv_corrupt.close()

    # =========================================================================
    # 3. 명세 4절 & 6.5절: apply_update 및 startup_housekeeping
    # =========================================================================

    def make_ready_staging(upd_folder: Path, base_folder: Path, ver: str = "1.2.0") -> Path:
        srv = LocalUpdateServer(support_range=True)
        try:
            z_b, m_b, s_b, _ = build_release_bundle(priv_key, v12_incremental_files, version=ver)
            u = srv.set_release(f"W.S.T-v{ver}-win64.zip", z_b, m_b, s_b, tag=f"v{ver}")
            return update.prepare(
                m_b, s_b, u["zip_url"], base_folder, upd_folder, "1.1.0", pubkey_b64=pub_b64, opener=srv.make_opener()
            )
        finally:
            srv.close()

    # [명세 4절, 8절] 정상 apply_update: 관리 대상 교체, 비관리 대상 유지, manifest에 없는 _internal 파일 제거
    base_apply = TEST_TMP_ROOT / "base_apply"
    upd_apply = TEST_TMP_ROOT / "upd_apply"
    setup_fake_installation(base_apply, v11_files, current_version="1.1.0")
    staging_apply = make_ready_staging(upd_apply, base_apply, ver="1.2.0")
    data_apply = base_apply / "data"

    try:
        res = update.apply_update(base_apply, staging_apply, data_apply, pubkey_b64=pub_b64)
        result_file = data_apply / "update_result.json"
        saved_res = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}

        managed_updated = (
            (base_apply / "W.S.T.exe").read_bytes() == v12_incremental_files["W.S.T.exe"]
            and (base_apply / "static" / "app.js").read_bytes() == v12_incremental_files["static/app.js"]
            and (base_apply / "static" / "new_feature.js").read_bytes() == v12_incremental_files["static/new_feature.js"]
        )
        obsolete_removed = not (base_apply / "_internal" / "obsolete.pyd").exists()
        unmanaged_preserved = (
            (base_apply / "data" / "user_db.json").read_text(encoding="utf-8") == '{"hosts": ["10.0.0.1"]}'
            and (base_apply / "logs" / "app.log").read_text(encoding="utf-8") == "log line 1\n"
            and (base_apply / "certs" / "localhost.pem").read_text(encoding="utf-8") == "-----BEGIN CERT-----"
            and (base_apply / "사용자메모.txt").read_text(encoding="utf-8") == "개인 메모 파일"
            and (base_apply / "실행.vbs").exists()
        )
        lock_removed = not (base_apply / ".wst-updating").exists()
        res_ok = (
            isinstance(res, dict)
            and res.get("ok") is True
            and saved_res.get("ok") is True
            and saved_res.get("to") == "1.2.0"
            and "from" in saved_res
            and "notes_url" in saved_res
            and "at" in saved_res
        )
        check("apply_update 관리 대상 파일 새 버전으로 교체", managed_updated)
        check("apply_update manifest에 없는 기존 _internal 파일 제거", obsolete_removed)
        check("apply_update data·logs·certs·사용자 파일·실행.vbs 보존", unmanaged_preserved)
        check("apply_update update_result.json(ok:true) 기록 및 잠금 해제", res_ok and lock_removed, f"res={saved_res}")
    except Exception as exc:
        check("apply_update 정상 적용", False, str(exc))

    # [명세 4절, 6.5절] startup_housekeeping: .wst-backup 삭제 및 update_result.json 반환 후 파일 삭제
    try:
        (base_apply / ".wst-backup").mkdir(exist_ok=True)
        (base_apply / ".wst-backup" / "dummy").write_text("bak", encoding="utf-8")
        hk_res = update.startup_housekeeping(base_apply, data_apply)
        check(
            "startup_housekeeping .wst-backup 삭제 및 update_result 반환·삭제",
            isinstance(hk_res, dict)
            and hk_res.get("ok") is True
            and not (base_apply / ".wst-backup").exists()
            and not (data_apply / "update_result.json").exists(),
        )
    except Exception as exc:
        check("startup_housekeeping .wst-backup 삭제 및 update_result 반환·삭제", False, str(exc))

    # [명세 4절 8항, 6.5절, 8절] 복사 도중 실패 주입(_copy 교체) → 원상 복구, update_result.json ok:false, staging 유지 및 3회 실패 시 포기
    base_fail = TEST_TMP_ROOT / "base_fail"
    upd_fail = TEST_TMP_ROOT / "upd_fail"
    setup_fake_installation(base_fail, v11_files, current_version="1.1.0")
    staging_fail = make_ready_staging(upd_fail, base_fail, ver="1.2.0")
    data_fail = base_fail / "data"

    orig_copy = getattr(update, "_copy", shutil.copy2)
    copy_call_count = 0

    def failing_copy(src, dst, *args, **kwargs):
        nonlocal copy_call_count
        copy_call_count += 1
        if copy_call_count >= 2:
            raise OSError("Simulated disk full during copy")
        return orig_copy(src, dst, *args, **kwargs)

    try:
        update._copy = failing_copy
        # 가정: apply_update는 실패 시 예외를 내부에서 잡아 {"ok": False, ...}를 반환하거나 예외를 던질 수 있으므로 둘 다 허용하되 결과 파일과 롤백 상태를 검증한다.
        try:
            fail_res = update.apply_update(base_fail, staging_fail, data_fail, pubkey_b64=pub_b64)
        except Exception:
            fail_res = None

        res_file = data_fail / "update_result.json"
        saved_fail = json.loads(res_file.read_text(encoding="utf-8")) if res_file.exists() else (fail_res or {})

        rolled_back = (
            (base_fail / "static" / "app.js").read_bytes() == v11_files["static/app.js"]
            and (base_fail / "_internal" / "obsolete.pyd").read_bytes() == v11_files["_internal/obsolete.pyd"]
            and not (base_fail / "static" / "new_feature.js").exists()
            and (base_fail / "data" / "user_db.json").exists()
        )
        lock_cleaned = not (base_fail / ".wst-updating").exists()
        staging_kept_after_1 = staging_fail.exists()
        result_ok_false = saved_fail.get("ok") is False and bool(saved_fail.get("error"))

        check(
            "apply_update 복사 실패 주입 시 원상 복구(롤백) 및 잠금 해제",
            rolled_back and lock_cleaned,
        )
        check(
            "apply_update 복사 실패 시 update_result.json(ok:false) 기록 및 1회 실패 후 staging 유지",
            result_ok_false and staging_kept_after_1,
            f"saved={saved_fail}",
        )

        # 2회, 3회 추가 실패 유도 후 같은 버전 포기 확인 (명세 4절 8항: 같은 버전 3회 실패하면 그 버전 포기)
        for _ in range(2):
            copy_call_count = 0
            try:
                update.apply_update(base_fail, staging_fail, data_fail, pubkey_b64=pub_b64)
            except Exception:
                pass

        # 가정: 3회 실패 후 포기 방식은 staging(또는 .ready)을 삭제하거나, 실패 카운터 기록으로 4번째 호출을 즉시 거부하는 방식 중 하나이다.
        update._copy = orig_copy
        abandoned = not staging_fail.exists() or not (staging_fail / ".ready").exists()
        if not abandoned:
            try:
                r4 = update.apply_update(base_fail, staging_fail, data_fail, pubkey_b64=pub_b64)
                abandoned = not (isinstance(r4, dict) and r4.get("ok") is True)
            except Exception:
                abandoned = True
        check("apply_update 같은 버전 3회 실패 시 그 버전 포기", abandoned)
    finally:
        update._copy = orig_copy

    # [명세 4절 2항, 8절] 잠금 파일(.wst-updating) 존재 시 동작: 10분 이내면 포기, 10분 넘으면 삭제 후 진행
    base_lock = TEST_TMP_ROOT / "base_lock"
    upd_lock = TEST_TMP_ROOT / "upd_lock"
    setup_fake_installation(base_lock, v11_files, current_version="1.1.0")
    staging_lock = make_ready_staging(upd_lock, base_lock, ver="1.2.0")
    data_lock = base_lock / "data"

    lock_file = base_lock / ".wst-updating"
    lock_file.write_text("locked", encoding="utf-8")

    try:
        try:
            lock_res = update.apply_update(base_lock, staging_lock, data_lock, pubkey_b64=pub_b64)
        except Exception:
            lock_res = {"ok": False}
        not_overwritten = (base_lock / "static" / "app.js").read_bytes() == v11_files["static/app.js"]
        check(
            "apply_update 10분 이내 .wst-updating 잠금 존재 시 포기",
            not_overwritten and (not isinstance(lock_res, dict) or lock_res.get("ok") is not True),
        )
    except Exception as exc:
        check("apply_update 10분 이내 .wst-updating 잠금 존재 시 포기", False, str(exc))

    # 잠금 파일 mtime을 15분 전으로 변경 → 삭제 후 정상 적용되어야 함
    old_time = time.time() - (15 * 60)
    os.utime(lock_file, (old_time, old_time))
    try:
        stale_res = update.apply_update(base_lock, staging_lock, data_lock, pubkey_b64=pub_b64)
        check(
            "apply_update 10분 경과한 .wst-updating 잠금은 삭제 후 정상 적용",
            isinstance(stale_res, dict)
            and stale_res.get("ok") is True
            and (base_lock / "static" / "app.js").read_bytes() == v12_incremental_files["static/app.js"],
        )
    except Exception as exc:
        check("apply_update 10분 경과한 .wst-updating 잠금은 삭제 후 정상 적용", False, str(exc))

    # [명세 4절 1항, 8절] wait_pid 시간 초과 시 포기
    base_pid = TEST_TMP_ROOT / "base_pid"
    upd_pid = TEST_TMP_ROOT / "upd_pid"
    setup_fake_installation(base_pid, v11_files, current_version="1.1.0")
    staging_pid = make_ready_staging(upd_pid, base_pid, ver="1.2.0")
    data_pid = base_pid / "data"

    try:
        # 현재 프로세스(os.getpid())는 종료되지 않으므로 timeout=0.2초 후 시간 초과로 포기해야 함
        try:
            pid_res = update.apply_update(
                base_pid, staging_pid, data_pid, wait_pid=os.getpid(), timeout=0.2, pubkey_b64=pub_b64
            )
        except Exception:
            pid_res = {"ok": False}
        untouched = (base_pid / "static" / "app.js").read_bytes() == v11_files["static/app.js"]
        check(
            "apply_update wait_pid 시간 초과 시 적용 포기 및 원본 유지",
            untouched and (not isinstance(pid_res, dict) or pid_res.get("ok") is not True),
        )
    except Exception as exc:
        check("apply_update wait_pid 시간 초과 시 적용 포기 및 원본 유지", False, str(exc))

    # =========================================================================
    # 4. 명세 3절, 8절 & 6.5절: 설정(autoUpdate 끔), 소스 실행(FROZEN=False), check_once
    # =========================================================================

    srv_chk = LocalUpdateServer(support_range=True)
    try:
        urls = srv_chk.set_release("W.S.T-v1.2.0-win64.zip", inc_zip, inc_m_bytes, inc_sig, tag="v1.2.0")
        opener = srv_chk.make_opener()

        base_cfg = TEST_TMP_ROOT / "base_cfg"
        upd_cfg = TEST_TMP_ROOT / "upd_cfg"
        data_cfg = base_cfg / "data"
        setup_fake_installation(base_cfg, v11_files, current_version="1.1.0")

        # [명세 3절, 8절] 소스 실행(common.FROZEN == False) → 동작 안 함(네트워크 요청 없음)
        srv_chk.clear_log()
        with set_frozen(False):
            st_src = update.check_once(
                base_cfg,
                data_cfg,
                upd_cfg,
                "1.1.0",
                latest_url=urls["latest_url"],
                pubkey_b64=pub_b64,
                opener=opener,
            )
        check(
            "소스 실행(FROZEN=False) 시 동작 안 함 및 네트워크 요청 없음",
            len(srv_chk.requests_log) == 0 and isinstance(st_src, dict) and st_src.get("state") == "disabled",
            f"state={st_src}, reqs={len(srv_chk.requests_log)}",
        )

        # [명세 3절, 8절] autoUpdate 끔 → 네트워크 요청 없음
        # 가정: 설정 파일 이름이 config.json 또는 settings.json일 수 있으므로 두 파일 모두에 autoUpdate: False를 기록한다.
        for cfg_name in ("config.json", "settings.json"):
            (data_cfg / cfg_name).write_text('{"autoUpdate": false, "auto_update": false}', encoding="utf-8")

        srv_chk.clear_log()
        with set_frozen(True):
            st_off = update.check_once(
                base_cfg,
                data_cfg,
                upd_cfg,
                "1.1.0",
                latest_url=urls["latest_url"],
                pubkey_b64=pub_b64,
                opener=opener,
            )
        check(
            "설정 autoUpdate 끔일 때 네트워크 요청 없음 및 disabled 반환",
            len(srv_chk.requests_log) == 0 and isinstance(st_off, dict) and st_off.get("state") == "disabled",
            f"state={st_off}, reqs={len(srv_chk.requests_log)}",
        )

        # autoUpdate 다시 켬
        for cfg_name in ("config.json", "settings.json"):
            (data_cfg / cfg_name).write_text('{"autoUpdate": true, "auto_update": true}', encoding="utf-8")

        # [명세 3절, 6.5절] check_once: 현재 버전이 이미 최신일 때 "latest" 반환
        srv_chk.clear_log()
        with set_frozen(True):
            st_latest = update.check_once(
                base_cfg,
                data_cfg,
                upd_cfg,
                "1.2.0",
                latest_url=urls["latest_url"],
                pubkey_b64=pub_b64,
                opener=opener,
            )
        check(
            "check_once 현재 버전이 최신이면 state='latest' 반환",
            isinstance(st_latest, dict) and st_latest.get("state") == "latest",
            f"state={st_latest}",
        )

        # [명세 3절, 6.5절] check_once: 새 버전이 있을 때 prepare 수행 후 state="ready" 반환 및 User-Agent·update_state.json 확인
        srv_chk.clear_log()
        with set_frozen(True):
            st_ready = update.check_once(
                base_cfg,
                data_cfg,
                upd_cfg,
                "1.1.0",
                latest_url=urls["latest_url"],
                pubkey_b64=pub_b64,
                opener=opener,
            )
        ua_ok = all(r["user_agent"] == "W.S.T-updater/1.1.0" for r in srv_chk.requests_log)
        state_file_ok = (data_cfg / "update_state.json").exists()
        check(
            "check_once 새 버전 준비 완료(state='ready'), User-Agent 준수 및 update_state.json 저장",
            isinstance(st_ready, dict)
            and st_ready.get("state") == "ready"
            and st_ready.get("version") == "1.2.0"
            and ua_ok
            and state_file_ok,
            f"state={st_ready}, ua_ok={ua_ok}, state_file_ok={state_file_ok}",
        )

        # [명세 8절] WST_UPDATE_URL, WST_UPDATE_PUBKEY 환경 변수는 FROZEN이 아닐 때만 반영(FROZEN=True에서는 무시)
        os.environ["WST_UPDATE_PUBKEY"] = pub_b64
        try:
            with set_frozen(True):
                # FROZEN=True이고 pubkey_b64=None이면 내장 UPDATE_PUBKEY를 써야 하므로 시험용 임시 키로 서명한 manifest는 거부되어야 함
                expect_update_error(
                    "FROZEN=True일 때 환경 변수 WST_UPDATE_PUBKEY 무시 확인",
                    lambda: update.verify_manifest(manifest_bytes, sig_bytes, "1.1.0", pubkey_b64=None),
                )
            with set_frozen(False):
                # FROZEN=False일 때는 WST_UPDATE_PUBKEY 환경 변수가 반영되어 통과해야 함
                try:
                    m_env = update.verify_manifest(manifest_bytes, sig_bytes, "1.1.0", pubkey_b64=None)
                    check(
                        "FROZEN=False일 때 환경 변수 WST_UPDATE_PUBKEY 반영 확인",
                        isinstance(m_env, dict) and m_env.get("version") == "1.2.0",
                    )
                except Exception as exc:
                    check("FROZEN=False일 때 환경 변수 WST_UPDATE_PUBKEY 반영 확인", False, str(exc))
        finally:
            os.environ.pop("WST_UPDATE_PUBKEY", None)

    finally:
        srv_chk.close()


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        shutil.rmtree(TEST_TMP_ROOT, ignore_errors=True)

    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{passed}/{total} 통과", flush=True)
    if passed < total:
        sys.exit(1)
