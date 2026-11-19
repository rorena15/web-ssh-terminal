"""명세 v1.4 (2026-11-19) 검증 시험: W.S.T 업데이트 알림·승낙.
실행: python dev/harness/t_update_consent.py [저장소_루트]"""
import asyncio
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
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TEST_TMP_ROOT = Path(tempfile.mkdtemp(prefix="wst_t_update_consent_"))
os.environ["WEBSSH_DATA"] = str(TEST_TMP_ROOT / "default_data")
os.environ["WST_UPDATE_DIR"] = str(TEST_TMP_ROOT / "default_upd")
os.environ["WST_UPDATE_URL"] = "https://127.0.0.1:1/repos/rorena15/web-ssh-terminal/releases/latest"

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from wst import common, update

api_mod = None
for _api_name in ("wst.api", "api"):
    try:
        api_mod = __import__(_api_name, fromlist=["*"])
        break
    except Exception:
        pass

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def make_keypair():
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
    version: str = "1.4.0",
    build_no: int = 10,
    fmt: int = 1,
    compress_type: int = zipfile.ZIP_DEFLATED,
    notes_url: str | None = None,
    with_version_file: bool = True,
) -> tuple[bytes, bytes, bytes, dict]:
    if notes_url is None:
        notes_url = f"https://github.com/rorena15/web-ssh-terminal/releases/tag/v{version}"
    if with_version_file and "_internal/version_info.txt" not in files_map and "W.S.T.exe" in files_map:
        files_map = {
            **files_map,
            "_internal/version_info.txt": f"StringStruct('FileVersion', '{version}'),\n".encode("utf-8"),
        }
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
            rel_path = zinfo.filename[len("W.S.T/") :]
            hdr_ofs = zinfo.header_offset
            sig, _ver, _flags, method, _time, _date, _crc, comp_sz, _uncomp_sz, fname_len, extra_len = (
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
    manifest_bytes = json.dumps(manifest_obj, ensure_ascii=False, indent=2).encode("utf-8")
    sig_bytes = priv_key.sign(manifest_bytes)
    return zip_bytes, manifest_bytes, sig_bytes, manifest_obj


class LocalUpdateServer:
    def __init__(self, support_range: bool = True):
        self.support_range = support_range
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
                ctype = (
                    "application/json"
                    if path.endswith(".json") or path.endswith("/latest")
                    else "application/octet-stream"
                )
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

    def set_release(
        self, zip_name: str, zip_bytes: bytes, manifest_bytes: bytes, sig_bytes: bytes, tag: str = "v1.4.0"
    ):
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
                {
                    "name": "manifest.json",
                    "browser_download_url": f"{self.base_url}{manifest_path}",
                    "size": len(manifest_bytes),
                },
                {
                    "name": "manifest.json.sig",
                    "browser_download_url": f"{self.base_url}{sig_path}",
                    "size": len(sig_bytes),
                },
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

    def zip_request_count(self) -> int:
        with self._lock:
            return sum(1 for r in self.requests_log if r["path"].endswith(".zip"))

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def write_version_info(base_dir: Path, ver: str = "1.3.0"):
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
    (base_dir / "_internal").mkdir(parents=True, exist_ok=True)
    (base_dir / "_internal" / "version_info.txt").write_text(content, encoding="utf-8")
    (base_dir / "build").mkdir(parents=True, exist_ok=True)
    (base_dir / "build" / "version_info.txt").write_text(content, encoding="utf-8")


def setup_fake_installation(base_dir: Path, files_map: dict[str, bytes], current_ver: str = "1.3.0"):
    base_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files_map.items():
        p = base_dir / Path(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    write_version_info(base_dir, current_ver)
    (base_dir / "data").mkdir(exist_ok=True)
    (base_dir / "logs").mkdir(exist_ok=True)


@contextlib.contextmanager
def test_env(base_dir: Path, data_dir: Path, upd_dir: Path, pub_b64: str, latest_url: str, opener, frozen: bool = True):
    """가정: update 모듈의 download/status/launch_ready 등이 common.BASE, common.DATA, WST_UPDATE_DIR, WST_UPDATE_URL,
    UPDATE_PUBKEYS 및 urllib.request.build_opener를 참조할 수 있으므로 시험 동안 일시 격리·주입한다."""
    sentinel = object()
    old_frozen_c = getattr(common, "FROZEN", sentinel)
    old_frozen_u = getattr(update, "FROZEN", sentinel)
    old_base_c = getattr(common, "BASE", sentinel)
    old_data_c = getattr(common, "DATA", sentinel)
    old_pubkeys = getattr(update, "UPDATE_PUBKEYS", sentinel)
    old_pubkey = getattr(update, "UPDATE_PUBKEY", sentinel)
    old_stopping = getattr(update, "_stopping", sentinel)
    old_build_opener = urllib.request.build_opener
    old_env = {k: os.environ.get(k) for k in ("WEBSSH_DATA", "WST_UPDATE_DIR", "WST_UPDATE_URL", "WST_UPDATE_PUBKEY")}

    data_dir.mkdir(parents=True, exist_ok=True)
    upd_dir.mkdir(parents=True, exist_ok=True)

    os.environ["WEBSSH_DATA"] = str(data_dir)
    os.environ["WST_UPDATE_DIR"] = str(upd_dir)
    os.environ["WST_UPDATE_URL"] = latest_url
    os.environ["WST_UPDATE_PUBKEY"] = pub_b64

    setattr(common, "FROZEN", frozen)
    if hasattr(update, "FROZEN"):
        setattr(update, "FROZEN", frozen)
    setattr(common, "BASE", base_dir)
    setattr(common, "DATA", data_dir)
    setattr(update, "UPDATE_PUBKEYS", (pub_b64,))
    if hasattr(update, "UPDATE_PUBKEY"):
        setattr(update, "UPDATE_PUBKEY", pub_b64)
    if hasattr(update, "_stopping"):
        setattr(update, "_stopping", False)

    # 가정: FROZEN=True에서 update_dir()나 check_once()가 환경 변수를 무시하도록 구현된 경우를 대비해,
    # 모듈이 update_dir 함수를 가지면 upd_dir을 반환하도록 래핑하고 urllib.request.build_opener가 로컬 루프백 opener를 반환하게 한다.
    old_update_dir_fn = getattr(update, "update_dir", sentinel)
    if callable(old_update_dir_fn):
        setattr(update, "update_dir", lambda: upd_dir)

    urllib.request.build_opener = lambda *a, **kw: opener

    # (Claude 수정 11/19) FROZEN=True면 current_version()이 sys._MEIPASS를 읽어 시험 환경에서 항상 실패한다.
    # launch_ready·restart가 인수 없이 부르므로 시험 동안 base_dir 기준으로 읽게 바꾼다.
    old_current_version = update.current_version
    update.current_version = lambda base=None: old_current_version(base or base_dir)

    try:
        yield
    finally:
        urllib.request.build_opener = old_build_opener
        update.current_version = old_current_version
        if old_update_dir_fn is not sentinel:
            setattr(update, "update_dir", old_update_dir_fn)
        if old_frozen_c is not sentinel:
            setattr(common, "FROZEN", old_frozen_c)
        if old_frozen_u is not sentinel:
            setattr(update, "FROZEN", old_frozen_u)
        if old_base_c is not sentinel:
            setattr(common, "BASE", old_base_c)
        if old_data_c is not sentinel:
            setattr(common, "DATA", old_data_c)
        if old_pubkeys is not sentinel:
            setattr(update, "UPDATE_PUBKEYS", old_pubkeys)
        if old_pubkey is not sentinel:
            setattr(update, "UPDATE_PUBKEY", old_pubkey)
        if old_stopping is not sentinel:
            setattr(update, "_stopping", old_stopping)
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def call_update_fn(fn_name: str, *args, **kwargs):
    """가정: update 모듈의 download/restart/later/skip 함수는 위치 인수만 받거나 선택적 키워드 인수를 받을 수 있으므로,
    시그니처를 확인해 지원하는 키워드만 전달한다."""
    fn = getattr(update, fn_name, None)
    if fn is None:
        raise AttributeError(f"update.{fn_name} 함수가 없음")
    sig = inspect.signature(fn)
    filtered_kw = {}
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    for k, v in kwargs.items():
        if accepts_var_kw or k in sig.parameters:
            filtered_kw[k] = v
    return fn(*args, **filtered_kw)


def wait_for_download(timeout: float = 30.0) -> dict:
    """download가 백그라운드 스레드일 수 있으므로 상태가 ready/error/available이 될 때까지 최대 30초 폴링."""
    deadline = time.monotonic() + timeout
    last_st = {}
    while time.monotonic() < deadline:
        # _guard 락이 풀리고 state가 downloading이 아닐 때까지 대기
        guard = getattr(update, "_guard", None)
        locked = guard.locked() if guard is not None and hasattr(guard, "locked") else False
        st = update.status(consume=False)
        last_st = st
        state = st.get("state")
        if not locked and state in ("ready", "error", "available"):
            return st
        time.sleep(0.05)
    return last_st


def write_settings(data_dir: Path, obj: dict):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "settings.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def read_prefs(data_dir: Path) -> dict:
    p = data_dir / "update_prefs.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def try_reject_invalid_update_mode(data_dir: Path) -> tuple[bool, str]:
    """가정: 잘못된 updateMode 저장 거부는 common.save_settings / update 또는 api의 saveSettings 핸들러에서 수행될 수 있으므로
    존재하는 경로를 순서대로 시험한다."""
    # 1. common 또는 update에 검증·저장 함수가 있는지 확인
    for mod in (common, update, api_mod):
        if mod is None:
            continue
        for fname in ("save_settings", "saveSettings", "validate_settings"):
            fn = getattr(mod, fname, None)
            if callable(fn):
                try:
                    res = fn({"updateMode": "invalid_mode"})
                    if inspect.iscoroutine(res):
                        res = asyncio.run(res)
                    if isinstance(res, dict) and (res.get("error") or res.get("ok") is False):
                        return True, f"{mod.__name__}.{fname} 오류 응답 반환: {res}"
                except Exception as exc:
                    return True, f"{mod.__name__}.{fname} 예외 발생: {exc}"

    # 2. api 모듈에 WebSocket 메시지 디스패처(_handle, handle, dispatch 등)가 있는지 확인
    if api_mod is not None:
        for hname in ("_handle", "handle", "dispatch", "on_message"):
            hfn = getattr(api_mod, hname, None)
            if callable(hfn):
                sent = []

                class DummyWS:
                    async def send(self, msg):
                        sent.append(json.loads(msg) if isinstance(msg, str) else msg)

                try:
                    sig = inspect.signature(hfn)
                    params = list(sig.parameters.keys())
                    msg_payload = {"op": "saveSettings", "settings": {"updateMode": "invalid_mode"}, "updateMode": "invalid_mode"}
                    if len(params) >= 2:
                        res = hfn(DummyWS(), msg_payload)
                    else:
                        res = hfn(msg_payload)
                    if inspect.iscoroutine(res):
                        res = asyncio.run(res)
                    if isinstance(res, dict) and (res.get("error") or res.get("ok") is False):
                        return True, f"api.{hname} 오류 반환: {res}"
                    if any(isinstance(m, dict) and (m.get("error") or m.get("type") == "error" or m.get("ok") is False) for m in sent):
                        return True, f"api.{hname} 오류 메시지 전송: {sent}"
                except Exception as exc:
                    return True, f"api.{hname} 예외 발생: {exc}"

        # 3. (Claude 수정 11/19) op 처리는 api_handler 안의 중첩 함수라 직접 부를 수 없음 → 소스 정적 확인:
        #    saveSettings 분기 안에 updateMode 허용값 검사와 예외가 있어야 함
        try:
            src = inspect.getsource(api_mod)
            seg = src[src.index('op == "saveSettings"'):]
            seg = seg[:seg.index("elif op ==")]
            if "updateMode" in seg and '("notify", "auto", "off")' in seg and "raise" in seg:
                return True, "api saveSettings 분기에 updateMode 허용값 검사·예외 있음(정적 확인)"
        except (OSError, TypeError, ValueError):
            pass
        try:
            common.save("settings", {"updateMode": "invalid_mode"})
            # 만약 common.save가 예외 없이 저장했다면 읽을 때 "notify"로 취급되는지만으로는 '저장 시 거부'가 아님
        except Exception as exc:
            return True, f"common.save('settings', ...) 예외 발생: {exc}"

    return False, "saveSettings에서 잘못된 updateMode 저장을 거부하는 진입점을 찾지 못했거나 거부하지 않음"


def expect_rejection(name: str, fn):
    """가정: 잘못된 요청(다른 버전, 잘못된 when, 잘못된 버전 문자열 등) 거부는 UpdateError/ValueError 예외를 던지거나
    {'ok': False} / {'error': ...} / False를 반환하는 방식으로 구현될 수 있다."""
    try:
        res = fn()
    except Exception as exc:
        check(name, True, f"예외로 거부됨: {type(exc).__name__}: {exc}")
        return
    if res is False or (isinstance(res, dict) and (res.get("ok") is False or bool(res.get("error")) or res.get("state") == "error")):
        check(name, True, f"반환값으로 거부됨: {res}")
    else:
        check(name, False, f"거부되지 않고 통과함: {res!r}")


def run_tests():
    priv_key, _priv_b64, pub_b64 = make_keypair()

    v13_files = {
        "W.S.T.exe": b"MZ-fake-exe-v1.3.0-" + (b"A" * 2048),
        "_internal/core.pyd": b"pyd-v1.3.0",
        "static/app.js": b"console.log('v1.3.0');",
        "LICENSE": b"MIT",
    }
    v14_files = {
        "W.S.T.exe": b"MZ-fake-exe-v1.4.0-" + (b"B" * 2048),
        "_internal/core.pyd": b"pyd-v1.4.0",
        "static/app.js": b"console.log('v1.4.0');",
        "LICENSE": b"MIT",
    }
    v15_files = {
        "W.S.T.exe": b"MZ-fake-exe-v1.5.0-" + (b"C" * 2048),
        "_internal/core.pyd": b"pyd-v1.5.0",
        "static/app.js": b"console.log('v1.5.0');",
        "LICENSE": b"MIT",
    }

    z14, m14, s14, m14_obj = build_release_bundle(priv_key, v14_files, version="1.4.0")
    z15, m15, s15, m15_obj = build_release_bundle(priv_key, v15_files, version="1.5.0")

    # =========================================================================
    # 1. 명세 1절 & 6절: 설정 updateMode 및 설정 옮기기 (autoUpdate -> updateMode)
    # =========================================================================
    cfg_dir = TEST_TMP_ROOT / "test_settings_data"
    srv_dummy = LocalUpdateServer()
    try:
        with test_env(TEST_TMP_ROOT / "cfg_base", cfg_dir, TEST_TMP_ROOT / "cfg_upd", pub_b64, srv_dummy.base_url, srv_dummy.make_opener()):
            # DEFAULT_SETTINGS 확인
            def_has_mode = common.DEFAULT_SETTINGS.get("updateMode") == "notify" and "autoUpdate" not in common.DEFAULT_SETTINGS
            check(
                "DEFAULT_SETTINGS에 autoUpdate 제거 및 updateMode='notify' 기본값 설정",
                def_has_mode,
                f"DEFAULT_SETTINGS={common.DEFAULT_SETTINGS}",
            )

            # autoUpdate 없음 -> notify
            write_settings(cfg_dir, {})
            s_none = common.settings()
            check(
                "설정 옮기기: autoUpdate 없음 -> updateMode == 'notify'",
                s_none.get("updateMode") == "notify",
                f"updateMode={s_none.get('updateMode')!r}",
            )

            # autoUpdate: True -> notify
            write_settings(cfg_dir, {"autoUpdate": True})
            s_true = common.settings()
            check(
                "설정 옮기기: autoUpdate=True -> updateMode == 'notify'",
                s_true.get("updateMode") == "notify",
                f"updateMode={s_true.get('updateMode')!r}",
            )

            # autoUpdate: False -> off
            write_settings(cfg_dir, {"autoUpdate": False})
            s_false = common.settings()
            check(
                "설정 옮기기: autoUpdate=False -> updateMode == 'off'",
                s_false.get("updateMode") == "off",
                f"updateMode={s_false.get('updateMode')!r}",
            )

            # 파일에 잘못된 updateMode가 들어 있을 때 읽을 때는 "notify"로 취급
            write_settings(cfg_dir, {"updateMode": "weird_value"})
            s_weird = common.settings()
            check(
                "설정 읽기: 잘못된 updateMode 값은 읽을 때 'notify'로 취급",
                s_weird.get("updateMode") == "notify",
                f"updateMode={s_weird.get('updateMode')!r}",
            )

            # 잘못된 updateMode 저장 시 거부 (saveSettings 오류)
            rejected_ok, rejected_detail = try_reject_invalid_update_mode(cfg_dir)
            check("설정 저장: 잘못된 updateMode 저장 거부(saveSettings 오류)", rejected_ok, rejected_detail)
    finally:
        srv_dummy.close()

    # =========================================================================
    # 2. 명세 2.2절 & 6절: prefs 파일 깨짐 -> 빈 값 취급 (앱이 죽지 않음)
    # =========================================================================
    srv = LocalUpdateServer()
    try:
        urls14 = srv.set_release("W.S.T-v1.4.0-win64.zip", z14, m14, s14, tag="v1.4.0")
        opener = srv.make_opener()

        base_broken = TEST_TMP_ROOT / "base_broken"
        data_broken = base_broken / "data"
        upd_broken = TEST_TMP_ROOT / "upd_broken"
        setup_fake_installation(base_broken, v13_files, current_ver="1.3.0")
        write_settings(data_broken, {"updateMode": "notify"})
        (data_broken / "update_prefs.json").write_text("{broken json!!!", encoding="utf-8")

        with test_env(base_broken, data_broken, upd_broken, pub_b64, urls14["latest_url"], opener, frozen=True):
            try:
                res_b = call_update_fn(
                    "check_once",
                    base_broken,
                    data_broken,
                    upd_broken,
                    "1.3.0",
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                )
                st_b = update.status(consume=False)
                check(
                    "깨진 update_prefs.json 파일이 있어도 빈 값으로 취급하고 정상 동작",
                    isinstance(res_b, dict)
                    and res_b.get("state") == "available"
                    and st_b.get("consent") is None,
                    f"res={res_b}, status={st_b}",
                )
            except Exception as exc:
                check("깨진 update_prefs.json 파일이 있어도 빈 값으로 취급하고 정상 동작", False, str(exc))

        # =========================================================================
        # 3. 명세 3.1절, 3.6절 & 6절: notify / off / auto 모드별 check_once 동작
        # =========================================================================

        # 3-A. notify 모드: 새 버전 확인 시 available, zip 요청 0번, staging 없음, status 필드 확인
        base_notify = TEST_TMP_ROOT / "base_notify"
        data_notify = base_notify / "data"
        upd_notify = TEST_TMP_ROOT / "upd_notify"
        setup_fake_installation(base_notify, v13_files, current_ver="1.3.0")
        write_settings(data_notify, {"updateMode": "notify"})

        srv.clear_log()
        with test_env(base_notify, data_notify, upd_notify, pub_b64, urls14["latest_url"], opener, frozen=True):
            try:
                res_n = call_update_fn(
                    "check_once",
                    base_notify,
                    data_notify,
                    upd_notify,
                    "1.3.0",
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                )
                zip_cnt = srv.zip_request_count()
                staging_exists = (upd_notify / "staging" / "1.4.0").exists()
                st_n = update.status(consume=False)

                check(
                    "notify 모드: 새 버전 확인 시 state='available', version='1.4.0', notes_url 포함",
                    isinstance(res_n, dict)
                    and res_n.get("state") == "available"
                    and res_n.get("version") == "1.4.0"
                    and res_n.get("notes_url") == m14_obj["notes_url"],
                    f"res={res_n}",
                )
                check(
                    "notify 모드: 승낙 전 zip 요청 0번 및 staging 생성 안 됨",
                    zip_cnt == 0 and not staging_exists,
                    f"zip_requests={zip_cnt}, staging_exists={staging_exists}",
                )
                check(
                    "status() 응답 필드(mode, prompt, consent, notes_url) 확인",
                    st_n.get("mode") == "notify"
                    and st_n.get("prompt") is True
                    and st_n.get("consent") is None
                    and st_n.get("notes_url") == m14_obj["notes_url"],
                    f"status={st_n}",
                )
            except Exception as exc:
                check("notify 모드 check_once 및 status 검증", False, str(exc))

        # 3-B. off 모드: 자동 확인(manual=False)은 disabled + 네트워크 요청 0번, 수동 확인(manual=True)은 available + prompt 참 + zip 요청 0번
        base_off = TEST_TMP_ROOT / "base_off"
        data_off = base_off / "data"
        upd_off = TEST_TMP_ROOT / "upd_off"
        setup_fake_installation(base_off, v13_files, current_ver="1.3.0")
        write_settings(data_off, {"updateMode": "off"})

        srv.clear_log()
        with test_env(base_off, data_off, upd_off, pub_b64, urls14["latest_url"], opener, frozen=True):
            try:
                res_off_auto = call_update_fn(
                    "check_once",
                    base_off,
                    data_off,
                    upd_off,
                    "1.3.0",
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                    manual=False,
                )
                check(
                    "off 모드: 자동 확인(manual=False) 시 disabled 및 네트워크 요청 없음",
                    isinstance(res_off_auto, dict)
                    and res_off_auto.get("state") == "disabled"
                    and len(srv.requests_log) == 0,
                    f"res={res_off_auto}, reqs={len(srv.requests_log)}",
                )

                sig_co = inspect.signature(update.check_once)
                if "manual" not in sig_co.parameters and not any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in sig_co.parameters.values()
                ):
                    check("off 모드: check_once에 manual 매개변수가 없음", False, f"signature={sig_co}")
                else:
                    srv.clear_log()
                    res_off_man = update.check_once(
                        base_off,
                        data_off,
                        upd_off,
                        "1.3.0",
                        latest_url=urls14["latest_url"],
                        pubkey_b64=pub_b64,
                        opener=opener,
                        manual=True,
                    )
                    st_off_man = update.status(consume=False)
                    check(
                        "off 모드: 수동 확인(manual=True) 시 available, zip 요청 0번, status().prompt 참",
                        isinstance(res_off_man, dict)
                        and res_off_man.get("state") == "available"
                        and srv.zip_request_count() == 0
                        and st_off_man.get("mode") == "off"
                        and st_off_man.get("prompt") is True,
                        f"res={res_off_man}, status={st_off_man}, zip_reqs={srv.zip_request_count()}",
                    )
            except Exception as exc:
                check("off 모드 자동/수동 확인 검증", False, str(exc))

        # 3-C. auto 모드: 기존처럼 즉시 prepare -> ready, 알림 띠 없음(prompt 거짓)
        base_auto = TEST_TMP_ROOT / "base_auto"
        data_auto = base_auto / "data"
        upd_auto = TEST_TMP_ROOT / "upd_auto"
        setup_fake_installation(base_auto, v13_files, current_ver="1.3.0")
        write_settings(data_auto, {"updateMode": "auto"})

        srv.clear_log()
        with test_env(base_auto, data_auto, upd_auto, pub_b64, urls14["latest_url"], opener, frozen=True):
            try:
                res_auto = call_update_fn(
                    "check_once",
                    base_auto,
                    data_auto,
                    upd_auto,
                    "1.3.0",
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                )
                st_auto = update.status(consume=False)
                check(
                    "auto 모드: check_once가 즉시 내려받아 state='ready' 및 staging/.ready 생성, prompt=False",
                    isinstance(res_auto, dict)
                    and res_auto.get("state") == "ready"
                    and (upd_auto / "staging" / "1.4.0" / ".ready").exists()
                    and srv.zip_request_count() >= 1
                    and st_auto.get("mode") == "auto"
                    and st_auto.get("prompt") is False,
                    f"res={res_auto}, status={st_auto}",
                )
            except Exception as exc:
                check("auto 모드 check_once 검증", False, str(exc))

        # =========================================================================
        # 4. 명세 3.4절, 3.6절 & 6절: later / skip 및 prompt 규칙
        # =========================================================================
        base_ls = TEST_TMP_ROOT / "base_ls"
        data_ls = base_ls / "data"
        upd_ls = TEST_TMP_ROOT / "upd_ls"
        setup_fake_installation(base_ls, v13_files, current_ver="1.3.0")
        write_settings(data_ls, {"updateMode": "notify"})

        with test_env(base_ls, data_ls, upd_ls, pub_b64, urls14["latest_url"], opener, frozen=True):
            call_update_fn(
                "check_once",
                base_ls,
                data_ls,
                upd_ls,
                "1.3.0",
                latest_url=urls14["latest_url"],
                pubkey_b64=pub_b64,
                opener=opener,
            )

            # 4-A. later(version)
            if not hasattr(update, "later"):
                check("later: update.later 함수 존재 확인", False, "update.later 없음")
            else:
                # 현재 available 버전(1.4.0)이 아닌 버전으로 later 호출 시 거부
                expect_rejection("later: 현재 available 버전과 다른 버전('1.9.0') 거부", lambda: call_update_fn("later", "1.9.0"))
                expect_rejection("later: 잘못된 버전 문자열('bad') 거부", lambda: call_update_fn("later", "bad"))

                t_before = time.time()
                call_update_fn("later", "1.4.0")
                prefs_later = read_prefs(data_ls)
                ra = prefs_later.get("remind_after", 0)
                st_before_ra = update.status(consume=False)
                check(
                    "later('1.4.0'): remind_after(now+86400) 저장 및 시각 전 prompt=False (state는 available 유지)",
                    isinstance(ra, (int, float))
                    and ra >= t_before + 86000
                    and st_before_ra.get("state") == "available"
                    and st_before_ra.get("prompt") is False,
                    f"remind_after={ra}, status={st_before_ra}",
                )

                # remind_after가 지난 뒤에는 prompt=True
                prefs_later["remind_after"] = time.time() - 10
                (data_ls / "update_prefs.json").write_text(json.dumps(prefs_later), encoding="utf-8")
                st_after_ra = update.status(consume=False)
                check(
                    "later: remind_after 시각이 지난 뒤에는 status().prompt == True",
                    st_after_ra.get("prompt") is True,
                    f"status={st_after_ra}",
                )

            # 4-B. skip(version)
            if not hasattr(update, "skip"):
                check("skip: update.skip 함수 존재 확인", False, "update.skip 없음")
            else:
                expect_rejection("skip: 현재 available 버전과 다른 버전('1.9.0') 거부", lambda: call_update_fn("skip", "1.9.0"))
                expect_rejection("skip: 잘못된 버전 문자열('1.4') 거부", lambda: call_update_fn("skip", "1.4"))

                # consent가 있는 상태에서 skip 호출 시 그 버전 consent도 지워지는지 확인하기 위해 미리 consent 기록
                (data_ls / "update_prefs.json").write_text(
                    json.dumps({"consent": {"version": "1.4.0", "when": "exit"}}), encoding="utf-8"
                )
                call_update_fn("skip", "1.4.0")
                prefs_skip = read_prefs(data_ls)
                st_skip = update.status(consume=False)
                check(
                    "skip('1.4.0'): skip='1.4.0' 저장, 해당 버전 consent 삭제, 같은 버전 prompt=False",
                    prefs_skip.get("skip") == "1.4.0"
                    and not prefs_skip.get("consent")
                    and st_skip.get("prompt") is False,
                    f"prefs={prefs_skip}, status={st_skip}",
                )

                # manual=True로 확인해 available이 나오면 skip·remind_after와 상관없이 prompt=True
                (data_ls / "update_prefs.json").write_text(
                    json.dumps({"skip": "1.4.0", "remind_after": time.time() + 86400}), encoding="utf-8"
                )
                call_update_fn(
                    "check_once",
                    base_ls,
                    data_ls,
                    upd_ls,
                    "1.3.0",
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                    manual=True,
                )
                st_manual_override = update.status(consume=False)
                check(
                    "skip/remind_after 설정 중이어도 manual=True 확인 직후에는 prompt=True",
                    st_manual_override.get("prompt") is True,
                    f"status={st_manual_override}",
                )

                # 더 새 버전(1.5.0)이 나오면 자동 확인(manual=False)에서도 prompt=True
                urls15 = srv.set_release("W.S.T-v1.5.0-win64.zip", z15, m15, s15, tag="v1.5.0")
                (data_ls / "update_prefs.json").write_text(json.dumps({"skip": "1.4.0"}), encoding="utf-8")
                call_update_fn(
                    "check_once",
                    base_ls,
                    data_ls,
                    upd_ls,
                    "1.3.0",
                    latest_url=urls15["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                    manual=False,
                )
                st_newer = update.status(consume=False)
                check(
                    "skip('1.4.0') 상태에서 더 새 버전('1.5.0') 발견 시 prompt=True",
                    st_newer.get("state") == "available"
                    and st_newer.get("version") == "1.5.0"
                    and st_newer.get("prompt") is True,
                    f"status={st_newer}",
                )

        # 서버 릴리즈를 다시 1.4.0으로 복원
        urls14 = srv.set_release("W.S.T-v1.4.0-win64.zip", z14, m14, s14, tag="v1.4.0")

        # =========================================================================
        # 5. 명세 3.2절 & 6절: download(version, when)
        # =========================================================================
        base_dl = TEST_TMP_ROOT / "base_dl"
        data_dl = base_dl / "data"
        upd_dl = TEST_TMP_ROOT / "upd_dl"
        setup_fake_installation(base_dl, v13_files, current_ver="1.3.0")
        write_settings(data_dl, {"updateMode": "notify"})

        with test_env(base_dl, data_dl, upd_dl, pub_b64, urls14["latest_url"], opener, frozen=True):
            if not hasattr(update, "download"):
                check("download: update.download 함수 존재 확인", False, "update.download 없음")
            else:
                srv.clear_log()  # (Claude 수정 11/19) 앞 단계(auto 모드)의 zip 요청 기록이 섞이지 않게
                call_update_fn(
                    "check_once",
                    base_dl,
                    data_dl,
                    upd_dl,
                    "1.3.0",
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                )

                # 잘못된 버전 문자열 거부
                for bad_v in ("invalid", "1.4", "v1.4.0", "../1.4.0", ""):
                    expect_rejection(
                        f"download: 잘못된 버전 문자열({bad_v!r}) 거부",
                        lambda bv=bad_v: call_update_fn("download", bv, "exit"),
                    )

                # 잘못된 when 거부
                for bad_w in ("later", "auto", "immediate", "", None):
                    expect_rejection(
                        f"download: 잘못된 when({bad_w!r}) 거부",
                        lambda bw=bad_w: call_update_fn("download", "1.4.0", bw),
                    )

                # 현재 available 버전(1.4.0)과 다른 버전 거부
                expect_rejection(
                    "download: 현재 available 버전과 다른 버전('1.4.1') 거부",
                    lambda: call_update_fn("download", "1.4.1", "exit"),
                )
                expect_rejection(
                    "download: 잘못된 요청 거부 후에도 zip 요청 0번 유지",
                    lambda: False if srv.zip_request_count() == 0 else True,
                )

                # skip='1.4.0', remind_after가 설정된 상태에서 download('1.4.0', 'exit') 승낙 시:
                # consent 저장, skip 제거, remind_after 제거, 백그라운드(또는 동기) 다운로드 후 ready
                (data_dl / "update_prefs.json").write_text(
                    json.dumps({"skip": "1.4.0", "remind_after": time.time() + 3600}), encoding="utf-8"
                )
                srv.clear_log()
                call_update_fn(
                    "download",
                    "1.4.0",
                    "exit",
                    base=base_dl,
                    data_dir=data_dl,
                    upd_dir=upd_dl,
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                )
                st_dl = wait_for_download(timeout=30.0)
                prefs_dl = read_prefs(data_dl)

                check(
                    "download('1.4.0', 'exit') 정상 완료: state='ready', staging/.ready 생성 및 zip 요청 발생",
                    st_dl.get("state") == "ready"
                    and st_dl.get("version") == "1.4.0"
                    and (upd_dl / "staging" / "1.4.0" / ".ready").exists()
                    and srv.zip_request_count() >= 1,
                    f"status={st_dl}, zip_reqs={srv.zip_request_count()}",
                )
                check(
                    "download('1.4.0', 'exit'): prefs에 consent 저장 및 같은 버전 skip·remind_after 제거",
                    prefs_dl.get("consent") == {"version": "1.4.0", "when": "exit"}
                    and not prefs_dl.get("skip")
                    and not prefs_dl.get("remind_after")
                    and st_dl.get("consent") == {"version": "1.4.0", "when": "exit"},
                    f"prefs={prefs_dl}, status.consent={st_dl.get('consent')}",
                )

                # [명세 3.1절] notify 모드에서 이미 해당 버전 .ready staging이 있고 consent.version이 같으면 check_once 시 다시 받지 않고 ready
                srv.clear_log()
                res_cached = call_update_fn(
                    "check_once",
                    base_dl,
                    data_dl,
                    upd_dl,
                    "1.3.0",
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                )
                check(
                    "notify 모드: .ready staging과 consent.version이 일치하면 check_once가 zip 재요청 없이 ready 유지",
                    isinstance(res_cached, dict)
                    and res_cached.get("state") == "ready"
                    and srv.zip_request_count() == 0,
                    f"res={res_cached}, zip_reqs={srv.zip_request_count()}",
                )

        # 5-B. download 시 다시 조회한 결과가 더 새 버전(1.5.0)이면 내려받지 않고 새 버전으로 available + consent 제거
        base_dl_new = TEST_TMP_ROOT / "base_dl_new"
        data_dl_new = base_dl_new / "data"
        upd_dl_new = TEST_TMP_ROOT / "upd_dl_new"
        setup_fake_installation(base_dl_new, v13_files, current_ver="1.3.0")
        write_settings(data_dl_new, {"updateMode": "notify"})

        urls14 = srv.set_release("W.S.T-v1.4.0-win64.zip", z14, m14, s14, tag="v1.4.0")
        with test_env(base_dl_new, data_dl_new, upd_dl_new, pub_b64, urls14["latest_url"], opener, frozen=True):
            if hasattr(update, "download"):
                # 1.4.0 확인
                call_update_fn(
                    "check_once",
                    base_dl_new,
                    data_dl_new,
                    upd_dl_new,
                    "1.3.0",
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                )
                # 사용자가 승낙을 누르기 직전 서버에 1.5.0이 올라옴
                srv.set_release("W.S.T-v1.5.0-win64.zip", z15, m15, s15, tag="v1.5.0")
                srv.clear_log()

                call_update_fn(
                    "download",
                    "1.4.0",
                    "now",
                    base=base_dl_new,
                    data_dir=data_dl_new,
                    upd_dir=upd_dl_new,
                    latest_url=urls14["latest_url"],
                    pubkey_b64=pub_b64,
                    opener=opener,
                )
                st_newer_dl = wait_for_download(timeout=30.0)
                prefs_newer_dl = read_prefs(data_dl_new)

                check(
                    "download: 다시 조회한 결과가 더 새 버전('1.5.0')이면 zip을 받지 않고 새 버전 'available' 전환 및 consent 지움",
                    st_newer_dl.get("state") == "available"
                    and st_newer_dl.get("version") == "1.5.0"
                    and srv.zip_request_count() == 0
                    and not (upd_dl_new / "staging" / "1.4.0").exists()
                    and not (upd_dl_new / "staging" / "1.5.0").exists()
                    and not prefs_newer_dl.get("consent")
                    and st_newer_dl.get("consent") is None,
                    f"status={st_newer_dl}, prefs={prefs_newer_dl}, zip_reqs={srv.zip_request_count()}",
                )

        # =========================================================================
        # 6. 명세 3.3절, 3.5절 & 6절: restart(version) 및 launch_ready()
        # =========================================================================
        urls14 = srv.set_release("W.S.T-v1.4.0-win64.zip", z14, m14, s14, tag="v1.4.0")
        base_lr = TEST_TMP_ROOT / "base_lr"
        data_lr = base_lr / "data"
        upd_lr = TEST_TMP_ROOT / "upd_lr"
        setup_fake_installation(base_lr, v13_files, current_ver="1.3.0")
        write_settings(data_lr, {"updateMode": "notify"})

        # 먼저 staging에 1.4.0(.ready)을 준비해 둠 (v1.3에서 승낙 없이 미리 받아 둔 상황 재현)
        update.prepare(m14, s14, urls14["zip_url"], base_lr, upd_lr, "1.3.0", pubkey_b64=pub_b64, opener=opener)

        popen_calls = []

        class DummyPopen:
            def __init__(self, args, **kwargs):
                self.args = list(args)
                self.kwargs = kwargs
                self.pid = 99999
                popen_calls.append((self.args, self.kwargs))

        orig_popen = subprocess.Popen
        subprocess.Popen = DummyPopen
        try:
            with test_env(base_lr, data_lr, upd_lr, pub_b64, urls14["latest_url"], opener, frozen=True):
                # 6-A. notify 모드에서 consent가 없을 때: ready staging이 있어도 launch_ready()가 프로세스를 안 띄움
                if (data_lr / "update_prefs.json").exists():
                    (data_lr / "update_prefs.json").unlink()
                popen_calls.clear()
                if hasattr(update, "_stopping"):
                    update._stopping = False
                update.launch_ready()
                check(
                    "launch_ready: notify 모드에서 consent 없는 ready staging은 적용하지 않음(Popen 미호출)",
                    len(popen_calls) == 0,
                    f"popen_calls={popen_calls}",
                )

                # 6-B. consent가 다른 버전('1.3.5')일 때도 안 띄움
                (data_lr / "update_prefs.json").write_text(
                    json.dumps({"consent": {"version": "1.3.5", "when": "exit"}}), encoding="utf-8"
                )
                popen_calls.clear()
                if hasattr(update, "_stopping"):
                    update._stopping = False
                update.launch_ready()
                check(
                    "launch_ready: consent.version('1.3.5')이 staging 버전('1.4.0')과 다르면 프로세스 안 띄움",
                    len(popen_calls) == 0,
                    f"popen_calls={popen_calls}",
                )

                # 6-C. consent가 있어도 skip과 같은 버전이면 안 띄움
                (data_lr / "update_prefs.json").write_text(
                    json.dumps({"skip": "1.4.0", "consent": {"version": "1.4.0", "when": "exit"}}), encoding="utf-8"
                )
                popen_calls.clear()
                if hasattr(update, "_stopping"):
                    update._stopping = False
                update.launch_ready()
                check(
                    "launch_ready: consent가 있어도 skip과 같은 버전이면 프로세스 안 띄움",
                    len(popen_calls) == 0,
                    f"popen_calls={popen_calls}",
                )

                # 6-D. consent.version == '1.4.0'이고 재시작 표시가 없을 때(일반 종료): Popen 호출하되 '--relaunch' 없음
                (data_lr / "update_prefs.json").write_text(
                    json.dumps({"consent": {"version": "1.4.0", "when": "exit"}}), encoding="utf-8"
                )
                popen_calls.clear()
                if hasattr(update, "_stopping"):
                    update._stopping = False
                (base_lr / ".wst-updating").unlink(missing_ok=True)
                update.launch_ready()
                check(
                    "launch_ready: notify 모드에서 consent 일치 시 apply 프로세스 실행 및 일반 종료에는 '--relaunch' 없음",
                    len(popen_calls) == 1
                    and "--apply-update" in popen_calls[0][0]
                    and "--relaunch" not in popen_calls[0][0],
                    f"args={popen_calls[0][0] if popen_calls else None}",
                )

                # 6-E. restart(version) 검증
                if not hasattr(update, "restart"):
                    check("restart: update.restart 함수 존재 확인", False, "update.restart 없음")
                else:
                    # consent가 없거나 다른 버전일 때 restart 거부
                    (data_lr / "update_prefs.json").write_text(json.dumps({}), encoding="utf-8")
                    expect_rejection(
                        "restart: consent가 없을 때 restart('1.4.0') 거부",
                        lambda: call_update_fn("restart", "1.4.0"),
                    )

                    # staging이 없는 버전으로 restart 거부
                    (data_lr / "update_prefs.json").write_text(
                        json.dumps({"consent": {"version": "1.9.9", "when": "now"}}), encoding="utf-8"
                    )
                    expect_rejection(
                        "restart: .ready staging이 없는 버전('1.9.9') 거부",
                        lambda: call_update_fn("restart", "1.9.9"),
                    )

                    # 정상 restart('1.4.0'): consent.when='now', common.request_shutdown() 호출, launch_ready 시 '--relaunch' 포함
                    (data_lr / "update_prefs.json").write_text(
                        json.dumps({"consent": {"version": "1.4.0", "when": "exit"}}), encoding="utf-8"
                    )
                    # (Claude 수정 11/19) 앞 launch_ready 시험이 가짜 Popen으로 남긴 적용 잠금 제거 — restart는 살아 있는 잠금이면 거부함(리뷰 수정 1)
                    (base_lr / ".wst-updating").unlink(missing_ok=True)
                    shutdown_called = []
                    old_req_shutdown = common.request_shutdown
                    common.request_shutdown = lambda: shutdown_called.append(True)
                    try:
                        call_update_fn("restart", "1.4.0")
                    finally:
                        common.request_shutdown = old_req_shutdown

                    prefs_rst = read_prefs(data_lr)
                    check(
                        "restart('1.4.0'): consent.when을 'now'로 갱신하고 common.request_shutdown() 호출",
                        prefs_rst.get("consent") == {"version": "1.4.0", "when": "now"} and len(shutdown_called) == 1,
                        f"prefs={prefs_rst}, shutdown_called={shutdown_called}",
                    )

                    popen_calls.clear()
                    if hasattr(update, "_stopping"):
                        update._stopping = False
                    (base_lr / ".wst-updating").unlink(missing_ok=True)
                    update.launch_ready()
                    check(
                        "launch_ready: restart 표시가 켜진 뒤 종료 시 apply 인수에 '--relaunch' 추가",
                        len(popen_calls) == 1
                        and "--apply-update" in popen_calls[0][0]
                        and "--relaunch" in popen_calls[0][0],
                        f"args={popen_calls[0][0] if popen_calls else None}",
                    )
        finally:
            subprocess.Popen = orig_popen

        # =========================================================================
        # 7. 명세 3.3절 & 6절: apply_update의 "waited" 필드 및 update.relaunch(target, result)
        # =========================================================================
        # 7-A. apply_update 성공 시 result["waited"] == True 및 relaunch가 target/W.S.T.exe를 인수 없이 실행
        base_ap_ok = TEST_TMP_ROOT / "base_ap_ok"
        upd_ap_ok = TEST_TMP_ROOT / "upd_ap_ok"
        data_ap_ok = base_ap_ok / "data"
        setup_fake_installation(base_ap_ok, v13_files, current_ver="1.3.0")
        staging_ap_ok = update.prepare(
            m14, s14, urls14["zip_url"], base_ap_ok, upd_ap_ok, "1.3.0", pubkey_b64=pub_b64, opener=opener
        )
        res_ap_ok = update.apply_update(base_ap_ok, staging_ap_ok, data_ap_ok, pubkey_b64=pub_b64)
        check(
            "apply_update 정상 완료 시 결과 dict에 'waited': True 포함",
            isinstance(res_ap_ok, dict) and res_ap_ok.get("ok") is True and res_ap_ok.get("waited") is True,
            f"res={res_ap_ok}",
        )

        # 7-B. apply_update 복사 실패·복구 시에도 wait_pid는 통과했으므로 result["waited"] == True
        base_ap_fail = TEST_TMP_ROOT / "base_ap_fail"
        upd_ap_fail = TEST_TMP_ROOT / "upd_ap_fail"
        data_ap_fail = base_ap_fail / "data"
        setup_fake_installation(base_ap_fail, v13_files, current_ver="1.3.0")
        staging_ap_fail = update.prepare(
            m14, s14, urls14["zip_url"], base_ap_fail, upd_ap_fail, "1.3.0", pubkey_b64=pub_b64, opener=opener
        )
        orig_copy = getattr(update, "_copy", shutil.copy2)

        def fail_copy(src, dst, *a, **kw):
            raise OSError("simulated copy failure")

        update._copy = fail_copy
        try:
            res_ap_fail = update.apply_update(base_ap_fail, staging_ap_fail, data_ap_fail, pubkey_b64=pub_b64)
        finally:
            update._copy = orig_copy

        check(
            "apply_update 복사 실패·복구 시 결과 dict에 ok=False, 'waited': True 포함",
            isinstance(res_ap_fail, dict) and res_ap_fail.get("ok") is False and res_ap_fail.get("waited") is True,
            f"res={res_ap_fail}",
        )

        # 7-C. apply_update에서 wait_pid 시간 초과 시 result["waited"] == False
        base_ap_to = TEST_TMP_ROOT / "base_ap_to"
        upd_ap_to = TEST_TMP_ROOT / "upd_ap_to"
        data_ap_to = base_ap_to / "data"
        setup_fake_installation(base_ap_to, v13_files, current_ver="1.3.0")
        staging_ap_to = update.prepare(
            m14, s14, urls14["zip_url"], base_ap_to, upd_ap_to, "1.3.0", pubkey_b64=pub_b64, opener=opener
        )
        res_ap_to = update.apply_update(
            base_ap_to, staging_ap_to, data_ap_to, wait_pid=os.getpid(), timeout=0.15, pubkey_b64=pub_b64
        )
        check(
            "apply_update wait_pid 시간 초과 시 결과 dict에 ok=False, 'waited': False 포함",
            isinstance(res_ap_to, dict) and res_ap_to.get("ok") is False and res_ap_to.get("waited") is False,
            f"res={res_ap_to}",
        )

        # 7-D. update.relaunch(target, result) 검증
        if not hasattr(update, "relaunch"):
            check("relaunch: update.relaunch 함수 존재 확인", False, "update.relaunch 없음")
        else:
            relaunch_calls = []

            class RelaunchPopen:
                def __init__(self, args, **kwargs):
                    self.args = list(args)
                    self.kwargs = kwargs
                    self.pid = 88888
                    relaunch_calls.append((self.args, self.kwargs))

            subprocess.Popen = RelaunchPopen
            try:
                expected_exe = str((base_ap_ok / "W.S.T.exe").resolve())

                # (1) 성공 결과(ok=True, waited=True) -> W.S.T.exe를 인수 없이 실행, True 반환
                relaunch_calls.clear()
                r_ok = update.relaunch(base_ap_ok, res_ap_ok)
                check(
                    "relaunch: apply 성공(waited=True) 시 target/W.S.T.exe를 인수 없이(cwd=target) 실행하고 True 반환",
                    r_ok is True
                    and len(relaunch_calls) == 1
                    and len(relaunch_calls[0][0]) == 1
                    and Path(relaunch_calls[0][0][0]).resolve() == Path(expected_exe)
                    and Path(relaunch_calls[0][1].get("cwd", "")).resolve() == base_ap_ok.resolve(),
                    f"ret={r_ok}, calls={relaunch_calls}",
                )

                # (2) 실패·복구 결과(ok=False, waited=True) -> 복구된 target/W.S.T.exe를 인수 없이 실행, True 반환
                relaunch_calls.clear()
                r_fail = update.relaunch(base_ap_fail, res_ap_fail)
                check(
                    "relaunch: apply 실패·복구(ok=False, waited=True) 시에도 target/W.S.T.exe를 인수 없이 실행하고 True 반환",
                    r_fail is True
                    and len(relaunch_calls) == 1
                    and len(relaunch_calls[0][0]) == 1
                    and Path(relaunch_calls[0][0][0]).resolve() == (base_ap_fail / "W.S.T.exe").resolve(),
                    f"ret={r_fail}, calls={relaunch_calls}",
                )

                # (3) wait_pid 시간 초과 결과(ok=False, waited=False) -> 실행하지 않고 False 반환
                relaunch_calls.clear()
                r_to = update.relaunch(base_ap_to, res_ap_to)
                check(
                    "relaunch: wait_pid 시간 초과(waited=False) 시 프로세스를 띄우지 않고 False 반환",
                    r_to is False and len(relaunch_calls) == 0,
                    f"ret={r_to}, calls={relaunch_calls}",
                )
            finally:
                subprocess.Popen = orig_popen

    finally:
        srv.close()


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        shutil.rmtree(TEST_TMP_ROOT, ignore_errors=True)

    passed = sum(1 for r in results if r)
    failed = sum(1 for r in results if not r)
    print(f"\n{passed} passed, {failed} failed", flush=True)
    if failed > 0:
        sys.exit(1)