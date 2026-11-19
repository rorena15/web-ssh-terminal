"""명세 v1.4 (2026-11-19) 7절 검증 시험: 업데이트 알림에 변경 내용(notes) 표시.
실행: python dev/harness/t_update_notes.py [저장소_루트]"""
import base64
import contextlib
import hashlib
import http.server
import inspect
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev" / "release"))

TEST_TMP_ROOT = Path(tempfile.mkdtemp(prefix="wst_t_update_notes_"))
os.environ["WEBSSH_DATA"] = str(TEST_TMP_ROOT / "default_data")
os.environ["WST_UPDATE_DIR"] = str(TEST_TMP_ROOT / "default_upd")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from wst import update

common_mod = None
for _mod_name in ("wst.common", "common"):
    try:
        common_mod = __import__(_mod_name, fromlist=["FROZEN", "BASE", "DATA"])
        break
    except Exception:
        pass

try:
    import make_manifest as make_manifest_mod
except Exception:
    make_manifest_mod = None

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def run_case(name: str, fn) -> None:
    try:
        ok, detail = fn()
        check(name, bool(ok), detail or "")
    except Exception as exc:
        check(name, False, f"{type(exc).__name__}: {exc}")


def make_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_b64 = base64.b64encode(priv.private_bytes_raw()).decode("ascii")
    pub_b64 = base64.b64encode(pub.public_bytes_raw()).decode("ascii")
    return priv, priv_b64, pub_b64


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_version_info_file(path: Path, ver: str = "1.4.0", build: int = 9) -> Path:
    parts = ver.split(".")
    assert len(parts) == 3
    nums = f"{parts[0]}, {parts[1]}, {parts[2]}, {build}"
    content = (
        f"VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums})),\n"
        f"  kids=[StringFileInfo([StringTable('040904B0', [\n"
        f"    StringStruct('FileVersion', '{ver}'),\n"
        f"    StringStruct('ProductVersion', '{ver}')])])]\n"
        f")\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def create_release_zip(zip_path: Path, ver: str = "1.4.0", build: int = 9) -> Path:
    ver_text = (
        f"VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers=(1, 4, 0, {build}), prodvers=(1, 4, 0, {build})),\n"
        f"  kids=[StringFileInfo([StringTable('040904B0', [\n"
        f"    StringStruct('FileVersion', '{ver}'),\n"
        f"    StringStruct('ProductVersion', '{ver}')])])]\n"
        f")\n"
    )
    files_map = {
        "W.S.T.exe": b"MZ-fake-exe-v" + ver.encode("ascii") + b"-" + (b"A" * 1024),
        "_internal/version_info.txt": ver_text.encode("utf-8"),
        "static/app.js": b"console.log('v1.4.0');",
        "LICENSE": b"MIT License",
    }
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in files_map.items():
            zinfo = zipfile.ZipInfo(f"W.S.T/{rel_path}")
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zinfo, content)
    return zip_path


def build_signed_bundle(
    priv_key: Ed25519PrivateKey,
    version: str = "1.4.0",
    build_no: int = 9,
    notes_field=...,
    override_manifest_fn=None,
) -> tuple[bytes, bytes, bytes, dict]:
    files_map = {
        "W.S.T.exe": b"MZ-fake-exe-v" + version.encode("ascii") + b"-" + (b"A" * 1024),
        "_internal/version_info.txt": f"StringStruct('FileVersion', '{version}'),\n".encode("utf-8"),
        "static/app.js": b"console.log('app');",
        "LICENSE": b"MIT",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in files_map.items():
            zinfo = zipfile.ZipInfo(f"W.S.T/{rel_path}")
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zinfo, content)
    zip_bytes = buf.getvalue()

    manifest_files = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for zinfo in zf.infolist():
            rel_path = zinfo.filename[len("W.S.T/"):]
            hdr_ofs = zinfo.header_offset
            sig, _v, _fl, method, _t, _d, _c, comp_sz, _uncomp_sz, fname_len, extra_len = (
                struct.unpack("<4s5H3I2H", zip_bytes[hdr_ofs : hdr_ofs + 30])
            )
            assert sig == b"PK\x03\x04"
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
        "format": 1,
        "version": version,
        "build": build_no,
        "published": "2026-11-19T00:00:00Z",
        "zip": {
            "name": f"W.S.T-v{version}-win64.zip",
            "size": len(zip_bytes),
            "sha256": sha256_hex(zip_bytes),
        },
        "files": manifest_files,
        "notes_url": f"https://github.com/rorena15/web-ssh-terminal/releases/tag/v{version}",
    }
    if notes_field is not ...:
        manifest_obj["notes"] = notes_field
    if override_manifest_fn is not None:
        override_manifest_fn(manifest_obj)

    manifest_bytes = json.dumps(manifest_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sig_bytes = priv_key.sign(manifest_bytes)
    return zip_bytes, manifest_bytes, sig_bytes, manifest_obj


class LocalUpdateServer:
    def __init__(self):
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
                with parent._lock:
                    parent.requests_log.append({"method": "GET", "path": path, "range": range_hdr})
                if path not in parent.routes:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = parent.routes[path]
                if range_hdr and range_hdr.startswith("bytes="):
                    m = re.match(r"^bytes=(\d+)-(\d+)$", range_hdr.strip())
                    if m:
                        start, end = int(m.group(1)), int(m.group(2))
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
        return f"https://127.0.0.1:{self.port}"

    def make_opener(self) -> urllib.request.OpenerDirector:
        class LocalLoopbackHandler(urllib.request.HTTPHandler):
            handler_order = 100

            def https_open(self, req):
                return self.http_open(req)

            def https_request(self, req):
                return self.http_request(req)

        return urllib.request.build_opener(LocalLoopbackHandler())

    def set_release(self, zip_name: str, zip_bytes: bytes, manifest_bytes: bytes, sig_bytes: bytes, tag: str = "v1.4.0"):
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

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def setup_fake_env(root_dir: Path, current_ver: str = "1.3.0") -> tuple[Path, Path, Path]:
    base_dir = root_dir / "base"
    data_dir = base_dir / "data"
    upd_dir = root_dir / "upd"
    base_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    upd_dir.mkdir(parents=True, exist_ok=True)

    (base_dir / "W.S.T.exe").write_bytes(b"MZ-fake-old-exe")
    write_version_info_file(base_dir / "_internal" / "version_info.txt", ver=current_ver, build=1)
    write_version_info_file(base_dir / "build" / "version_info.txt", ver=current_ver, build=1)
    (data_dir / "settings.json").write_text('{"updateMode": "notify"}', encoding="utf-8")
    return base_dir, data_dir, upd_dir


@contextlib.contextmanager
def patched_env(base_dir: Path, data_dir: Path, upd_dir: Path, pub_b64: str, frozen: bool = True):
    """FROZEN, common.BASE, common.DATA, UPDATE_PUBKEYS 및 current_version(base 폴더 기준)을 일시 교체하고 원복한다."""
    sentinel = object()
    old_common_frozen = getattr(common_mod, "FROZEN", sentinel) if common_mod else sentinel
    old_common_base = getattr(common_mod, "BASE", sentinel) if common_mod else sentinel
    old_common_data = getattr(common_mod, "DATA", sentinel) if common_mod else sentinel
    old_update_frozen = getattr(update, "FROZEN", sentinel)
    old_pubkeys = getattr(update, "UPDATE_PUBKEYS", sentinel)
    old_current_version = update.current_version
    old_status = dict(getattr(update, "_status", {}))
    old_manual = getattr(update, "_manual_prompt", False)
    old_upd_env = os.environ.get("WST_UPDATE_DIR")

    def _patched_current_version(base=None):
        target_base = Path(base) if base is not None else base_dir
        return old_current_version(target_base)

    try:
        if common_mod is not None:
            setattr(common_mod, "FROZEN", frozen)
            setattr(common_mod, "BASE", base_dir)
            setattr(common_mod, "DATA", data_dir)
        if hasattr(update, "FROZEN") or common_mod is None:
            setattr(update, "FROZEN", frozen)
        setattr(update, "UPDATE_PUBKEYS", (pub_b64,))
        update.current_version = _patched_current_version
        update._status = {}
        update._manual_prompt = False
        os.environ["WST_UPDATE_DIR"] = str(upd_dir)
        yield
    finally:
        update.current_version = old_current_version
        update._status = old_status
        update._manual_prompt = old_manual
        if old_upd_env is None:
            os.environ.pop("WST_UPDATE_DIR", None)
        else:
            os.environ["WST_UPDATE_DIR"] = old_upd_env
        if old_pubkeys is not sentinel:
            setattr(update, "UPDATE_PUBKEYS", old_pubkeys)
        if common_mod is not None:
            if old_common_frozen is not sentinel:
                setattr(common_mod, "FROZEN", old_common_frozen)
            if old_common_base is not sentinel:
                setattr(common_mod, "BASE", old_common_base)
            if old_common_data is not sentinel:
                setattr(common_mod, "DATA", old_common_data)
        if old_update_frozen is sentinel:
            if hasattr(update, "FROZEN"):
                delattr(update, "FROZEN")
        else:
            setattr(update, "FROZEN", old_update_frozen)


def run_make_manifest(
    zip_path: Path,
    version_file: Path,
    tag: str,
    output_path: Path,
    notes_arg: Path | None = ...,
    cwd: Path | None = None,
) -> dict:
    """make_manifest.py를 subprocess 또는 import된 함수로 실행해 생성된 manifest dict를 반환한다."""
    script_path = ROOT / "dev" / "release" / "make_manifest.py"
    if not script_path.exists() and (ROOT / "make_manifest.py").exists():
        script_path = ROOT / "make_manifest.py"

    if script_path.exists():
        cmd = [
            sys.executable,
            str(script_path),
            "--zip",
            str(zip_path),
            "--version-file",
            str(version_file),
            "--tag",
            tag,
            "--output",
            str(output_path),
        ]
        if notes_arg is not ... and notes_arg is not None:
            cmd.extend(["--notes", str(notes_arg)])
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or TEST_TMP_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"make_manifest exit {proc.returncode}: {proc.stderr or proc.stdout}")
        return json.loads(output_path.read_text(encoding="utf-8"))

    if make_manifest_mod is None:
        raise RuntimeError("make_manifest 모듈을 찾을 수 없음")
    fn = make_manifest_mod.make_manifest
    sig = inspect.signature(fn)
    if notes_arg is not ... and len(sig.parameters) >= 4:
        return fn(zip_path, version_file, tag, notes_arg)
    return fn(zip_path, version_file, tag)


def run_tests():
    priv_key, _priv_b64, pub_b64 = make_keypair()

    # =========================================================================
    # 1. 명세 7.1 & 7.3: make_manifest 시험
    # =========================================================================
    mm_dir = TEST_TMP_ROOT / "make_manifest_cases"
    mm_dir.mkdir(parents=True, exist_ok=True)
    zip_v140 = create_release_zip(mm_dir / "W.S.T-v1.4.0-win64.zip", ver="1.4.0", build=9)
    ver_v140 = write_version_info_file(mm_dir / "version_info.txt", ver="1.4.0", build=9)

    # 1-1. --notes 파일 지정 -> ko/en 분리, 맨 앞 '## W.S.T v...' 제목 줄 제거, 앞뒤 빈 줄 제거
    def _case_mm_split_and_strip():
        notes_file = mm_dir / "notes_valid.md"
        notes_content = (
            "\n\n"
            "## W.S.T v1.4.0 변경 사항\n"
            "\n"
            "### 주요 기능\n"
            "- 알림 후 승낙 시 내려받기\n"
            "  - 변경 내용 앱 안 표시\n"
            "\n"
            "---\n"
            "\n"
            "## W.S.T v1.4.0 Release Notes\n"
            "\n"
            "### Highlights\n"
            "- Download only after user consent\n"
            "  - Show release notes inside the app\n"
            "\n\n"
        )
        notes_file.write_text(notes_content, encoding="utf-8")
        out_json = mm_dir / "manifest_valid.json"
        m = run_make_manifest(zip_v140, ver_v140, "v1.4.0", out_json, notes_arg=notes_file, cwd=mm_dir)
        notes = m.get("notes")
        expected_ko = "### 주요 기능\n- 알림 후 승낙 시 내려받기\n  - 변경 내용 앱 안 표시"
        expected_en = "### Highlights\n- Download only after user consent\n  - Show release notes inside the app"
        ok = (
            isinstance(notes, dict)
            and notes.get("ko") == expected_ko
            and notes.get("en") == expected_en
        )
        return ok, f"notes={notes!r}"

    run_case("make_manifest --notes 파일 ko/en 분리 및 제목·앞뒤 빈 줄 제거", _case_mm_split_and_strip)

    # 1-2. --notes 생략 시 기본 경로 docs/release-notes/v{version}.md 자동 사용
    def _case_mm_default_path():
        def_work = mm_dir / "default_cwd"
        def_notes = def_work / "docs" / "release-notes" / "v1.4.0.md"
        def_notes.parent.mkdir(parents=True, exist_ok=True)
        def_notes.write_text(
            "## W.S.T v1.4.0\n- 기본 경로 한국어 항목\n---\n## W.S.T v1.4.0\n- Default path English item\n",
            encoding="utf-8",
        )
        out_json = def_work / "manifest_default.json"
        m = run_make_manifest(zip_v140, ver_v140, "v1.4.0", out_json, notes_arg=..., cwd=def_work)
        notes = m.get("notes")
        ok = (
            isinstance(notes, dict)
            and notes.get("ko") == "- 기본 경로 한국어 항목"
            and notes.get("en") == "- Default path English item"
        )
        return ok, f"notes={notes!r}"

    run_case("make_manifest --notes 미지정 시 기본 경로(docs/release-notes/v1.4.0.md) 사용", _case_mm_default_path)

    # 1-3. 각 부분(ko 또는 en)이 8000자를 넘으면 실패(빌드 중단)
    def _case_mm_over_8000_ko():
        notes_over_ko = mm_dir / "notes_over_ko.md"
        notes_over_ko.write_text("## W.S.T v1.4.0\n" + ("가" * 8001) + "\n---\n## W.S.T v1.4.0\n- ok\n", encoding="utf-8")
        out_json = mm_dir / "manifest_over_ko.json"
        try:
            run_make_manifest(zip_v140, ver_v140, "v1.4.0", out_json, notes_arg=notes_over_ko, cwd=mm_dir)
        except Exception as exc:
            return True, f"예상대로 실패: {exc}"
        return False, "ko 8001자 초과인데 실패하지 않고 통과함"

    run_case("make_manifest ko 8000자 초과 시 실패(빌드 중단)", _case_mm_over_8000_ko)

    def _case_mm_over_8000_en():
        notes_over_en = mm_dir / "notes_over_en.md"
        notes_over_en.write_text("## W.S.T v1.4.0\n- 정상\n---\n## W.S.T v1.4.0\n" + ("A" * 8001) + "\n", encoding="utf-8")
        out_json = mm_dir / "manifest_over_en.json"
        try:
            run_make_manifest(zip_v140, ver_v140, "v1.4.0", out_json, notes_arg=notes_over_en, cwd=mm_dir)
        except Exception as exc:
            return True, f"예상대로 실패: {exc}"
        return False, "en 8001자 초과인데 실패하지 않고 통과함"

    run_case("make_manifest en 8000자 초과 시 실패(빌드 중단)", _case_mm_over_8000_en)

    # 1-4. 파일이 없으면 notes 키를 넣지 않음 (기본 경로도 없고 지정 파일도 없는 경우)
    def _case_mm_no_file():
        empty_work = mm_dir / "empty_cwd"
        empty_work.mkdir(parents=True, exist_ok=True)
        out_json = empty_work / "manifest_no_notes.json"
        m = run_make_manifest(zip_v140, ver_v140, "v1.4.0", out_json, notes_arg=..., cwd=empty_work)
        ok = "notes" not in m
        return ok, f"keys={sorted(m.keys())}"

    run_case("make_manifest 노트 파일이 없으면 manifest에 notes를 넣지 않음", _case_mm_no_file)

    def _case_mm_explicit_missing_file():
        empty_work = mm_dir / "empty_cwd2"
        empty_work.mkdir(parents=True, exist_ok=True)
        missing_path = empty_work / "nonexistent_notes.md"
        out_json = empty_work / "manifest_missing_arg.json"
        # (Claude 수정 11/19) 2차 리뷰 D(사용자 승인): 명시한 --notes 파일이 없으면 경로 오타를 놓치지 않게 빌드 실패
        try:
            run_make_manifest(zip_v140, ver_v140, "v1.4.0", out_json, notes_arg=missing_path, cwd=empty_work)
        except Exception as exc:
            return "FileNotFoundError" in str(exc), f"예상대로 실패: {str(exc)[-200:]}"
        return False, "지정 파일이 없는데 통과함"

    run_case("make_manifest --notes 지정 파일이 존재하지 않으면 빌드 실패", _case_mm_explicit_missing_file)

    # =========================================================================
    # 2. 명세 7.1 & 7.3: verify_manifest 시험
    # =========================================================================

    # 2-1. 올바른 notes(ko/en 모두, ko만, en만, 경계값 8000자) 통과 및 보존
    def _case_vm_valid_notes():
        valid_notes = {"ko": "- 한국어 변경 내역\n\t- 탭 포함 줄", "en": "- English release notes\n\t- Tabbed line"}
        _, m_bytes, sig_bytes, _ = build_signed_bundle(priv_key, version="1.4.0", notes_field=valid_notes)
        parsed = update.verify_manifest(m_bytes, sig_bytes, "1.3.0", pubkey_b64=pub_b64)
        ok = parsed.get("version") == "1.4.0" and parsed.get("notes") == valid_notes
        return ok, f"notes={parsed.get('notes')!r}"

    run_case("verify_manifest 올바른 notes(ko·en) 통과 및 보존", _case_vm_valid_notes)

    def _case_vm_8000_boundary():
        boundary_notes = {"ko": "가" * 8000, "en": "A" * 8000}
        _, m_bytes, sig_bytes, _ = build_signed_bundle(priv_key, version="1.4.0", notes_field=boundary_notes)
        parsed = update.verify_manifest(m_bytes, sig_bytes, "1.3.0", pubkey_b64=pub_b64)
        notes = parsed.get("notes", {})
        ok = isinstance(notes, dict) and len(notes.get("ko", "")) == 8000 and len(notes.get("en", "")) == 8000
        return ok, f"ko_len={len(notes.get('ko', ''))}, en_len={len(notes.get('en', ''))}"

    run_case("verify_manifest 정확히 8000자 notes 통과 및 보존", _case_vm_8000_boundary)

    # 2-2. 잘못된 형식(리스트, 숫자 값, 다른 키, 8001자) -> manifest는 통과하고 notes만 버림
    invalid_notes_cases = [
        ("리스트 형식(['- 항목'])", ["- 항목"]),
        ("문자열 형식('notes')", "just a string"),
        ("숫자 값({'ko': 123})", {"ko": 123}),
        ("불리언 값({'en': True})", {"en": True}),
        ("허용되지 않은 다른 키({'ko': 'ok', 'ja': 'ng'})", {"ko": "ok", "ja": "ng"}),
        ("허용되지 않은 단일 키({'fr': 'bonjour'})", {"fr": "bonjour"}),
        ("8001자 초과({'ko': 8001자})", {"ko": "가" * 8001}),
        ("8001자 초과({'en': 8001자})", {"en": "A" * 8001}),
    ]
    for label, bad_notes in invalid_notes_cases:
        def _case_vm_bad(bn=bad_notes):
            _, m_bytes, sig_bytes, _ = build_signed_bundle(priv_key, version="1.4.0", notes_field=bn)
            parsed = update.verify_manifest(m_bytes, sig_bytes, "1.3.0", pubkey_b64=pub_b64)
            # 명세 7.1: "어기면 manifest 전체를 거부하지 말고 notes만 버린다"
            notes_after = parsed.get("notes")
            dropped = ("notes" not in parsed) or not notes_after
            ok = isinstance(parsed, dict) and parsed.get("version") == "1.4.0" and dropped
            return ok, f"version={parsed.get('version')}, notes={notes_after!r}"

        run_case(f"verify_manifest 잘못된 notes 형식 시 manifest 통과 및 notes만 제거: {label}", _case_vm_bad)

    # 2-3. 제어 문자(\t, \n 제외) 제거 확인 (\r, \x00, \x07, \x1b, \x7f 등 제거되고 \t, \n은 유지)
    def _case_vm_strip_control_chars():
        raw_ko = "첫째 줄\r\n\t둘째\x00줄\x07벨\x1b[31m색상\x1f끝\x7f"
        raw_en = "Line 1\r\n\tLine\x002\x08bell\x1b[0mEnd\x7f"
        _, m_bytes, sig_bytes, _ = build_signed_bundle(
            priv_key, version="1.4.0", notes_field={"ko": raw_ko, "en": raw_en}
        )
        parsed = update.verify_manifest(m_bytes, sig_bytes, "1.3.0", pubkey_b64=pub_b64)
        notes = parsed.get("notes", {})
        expected_ko = "첫째 줄\n\t둘째줄벨[31m색상끝"
        expected_en = "Line 1\n\tLine2bell[0mEnd"
        ok = (
            isinstance(notes, dict)
            and notes.get("ko") == expected_ko
            and notes.get("en") == expected_en
        )
        return ok, f"notes={notes!r}"

    run_case("verify_manifest 제어 문자(\\t·\\n 제외) 제거 및 \\t·\\n 보존", _case_vm_strip_control_chars)

    # 2-4. 서명된 manifest의 notes를 바꾸면 서명 검증 실패(UpdateError)
    def _case_vm_tamper_notes_fails_sig():
        _, m_bytes, sig_bytes, _ = build_signed_bundle(
            priv_key, version="1.4.0", notes_field={"ko": "- 원본 변경 내용", "en": "- Original notes"}
        )
        tampered_obj = json.loads(m_bytes.decode("utf-8"))
        tampered_obj["notes"]["ko"] = "- 변조된 변경 내용"
        tampered_bytes = json.dumps(tampered_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            update.verify_manifest(tampered_bytes, sig_bytes, "1.3.0", pubkey_b64=pub_b64)
        except update.UpdateError as exc:
            return True, f"UpdateError 발생: {exc}"
        return False, "notes 변조 후에도 UpdateError가 발생하지 않음"

    run_case("verify_manifest notes 변조 시 서명 검증 실패(UpdateError)", _case_vm_tamper_notes_fails_sig)

    # =========================================================================
    # 3. 명세 7.2 & 7.3: check_once(notify, 로컬 HTTP 서버) 및 status()의 notes
    #    (ko 우선, en 대체, 둘 다 없으면 "", update_state.json 저장)
    # =========================================================================
    srv = LocalUpdateServer()
    try:
        opener = srv.make_opener()

        # 3-1. ko와 en이 모두 있을 때 -> ko 우선
        def _case_check_ko_priority():
            base_dir, data_dir, upd_dir = setup_fake_env(TEST_TMP_ROOT / "env_ko_prio", current_ver="1.3.0")
            notes_both = {"ko": "- 한국어 우선 표시", "en": "- English fallback"}
            z_b, m_b, s_b, _ = build_signed_bundle(priv_key, version="1.4.0", notes_field=notes_both)
            urls = srv.set_release("W.S.T-v1.4.0-win64.zip", z_b, m_b, s_b, tag="v1.4.0")

            with patched_env(base_dir, data_dir, upd_dir, pub_b64, frozen=True):
                res = update.check_once(
                    base_dir,
                    data_dir,
                    upd_dir,
                    "1.3.0",
                    latest_url=urls["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                    manual=False,
                )
                st = update.status(consume=False, base=base_dir, data_dir=data_dir, pubkey_b64=pub_b64)
                saved = json.loads((data_dir / "update_state.json").read_text(encoding="utf-8"))

            ok = (
                res.get("state") == "available"
                and res.get("notes") == "- 한국어 우선 표시"
                and st.get("state") == "available"
                and st.get("notes") == "- 한국어 우선 표시"
                and saved.get("notes") == "- 한국어 우선 표시"
            )
            return ok, f"res_notes={res.get('notes')!r}, st_notes={st.get('notes')!r}, saved_notes={saved.get('notes')!r}"

        run_case("check_once(notify) & status(): ko/en 모두 있을 때 ko 우선 및 update_state.json 반영", _case_check_ko_priority)

        # 3-2. ko가 없고 en만 있을 때 -> en 대체
        def _case_check_en_fallback():
            base_dir, data_dir, upd_dir = setup_fake_env(TEST_TMP_ROOT / "env_en_fall", current_ver="1.3.0")
            notes_en_only = {"en": "- English only release notes"}
            z_b, m_b, s_b, _ = build_signed_bundle(priv_key, version="1.4.0", notes_field=notes_en_only)
            urls = srv.set_release("W.S.T-v1.4.0-win64.zip", z_b, m_b, s_b, tag="v1.4.0")

            with patched_env(base_dir, data_dir, upd_dir, pub_b64, frozen=True):
                res = update.check_once(
                    base_dir,
                    data_dir,
                    upd_dir,
                    "1.3.0",
                    latest_url=urls["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                    manual=True,
                )
                st = update.status(consume=False, base=base_dir, data_dir=data_dir, pubkey_b64=pub_b64)
                saved = json.loads((data_dir / "update_state.json").read_text(encoding="utf-8"))

            ok = (
                res.get("state") == "available"
                and res.get("notes") == "- English only release notes"
                and st.get("notes") == "- English only release notes"
                and saved.get("notes") == "- English only release notes"
            )
            return ok, f"res_notes={res.get('notes')!r}, st_notes={st.get('notes')!r}"

        run_case("check_once(notify, manual=True) & status(): ko 없을 때 en 대체", _case_check_en_fallback)

        # 3-3. notes가 아예 없을 때 -> 빈 문자열 ""
        def _case_check_none_empty_str():
            base_dir, data_dir, upd_dir = setup_fake_env(TEST_TMP_ROOT / "env_no_notes", current_ver="1.3.0")
            z_b, m_b, s_b, _ = build_signed_bundle(priv_key, version="1.4.0", notes_field=...)
            urls = srv.set_release("W.S.T-v1.4.0-win64.zip", z_b, m_b, s_b, tag="v1.4.0")

            with patched_env(base_dir, data_dir, upd_dir, pub_b64, frozen=True):
                res = update.check_once(
                    base_dir,
                    data_dir,
                    upd_dir,
                    "1.3.0",
                    latest_url=urls["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                    manual=False,
                )
                st = update.status(consume=False, base=base_dir, data_dir=data_dir, pubkey_b64=pub_b64)
                saved = json.loads((data_dir / "update_state.json").read_text(encoding="utf-8"))

            ok = (
                res.get("state") == "available"
                and res.get("notes") == ""
                and st.get("notes") == ""
                and saved.get("notes") == ""
            )
            return ok, f"res_notes={res.get('notes')!r}, st_notes={st.get('notes')!r}, saved_notes={saved.get('notes')!r}"

        run_case("check_once(notify) & status(): manifest에 notes가 없으면 빈 문자열('')", _case_check_none_empty_str)

    finally:
        srv.close()


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        shutil.rmtree(TEST_TMP_ROOT, ignore_errors=True)

    passed = sum(1 for r in results if r)
    failed = sum(1 for r in results if not r)
    print(f"{passed} passed, {failed} failed", flush=True)
    if failed > 0:
        sys.exit(1)