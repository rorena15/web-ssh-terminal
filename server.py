"""W.S.T — 브라우저 SSH 클라이언트의 중계 서버.

실행:  python server.py --open  → 크롬 앱 창
       python server.py         → http://127.0.0.1:8022 (이 PC에서만)

WebSocket 경로
  /ws     SSH 터미널 (term.py)          /sftp   SFTP (sftp.py, 터미널 세션에 붙음)
  /local  로컬 터미널 (localterm.py)    /api    세션 트리·설정·터널·RDP (api.py)

보안 메모
- 루프백 바인딩만 허용. Host 검사로 DNS 리바인딩 차단.
- WebSocket Origin 검사로 CSWSH 차단. 비밀번호/키 암호는 저장하지 않음.
- 호스트 키 TOFU (known_hosts), 키가 바뀌면 접속 거부.
"""
import argparse
import asyncio
import hmac
import logging
import mimetypes
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import webbrowser
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit, parse_qsl, urlencode

from wst import common
from wst import foreground

APP_NAME = "W.S.T"
HIDDEN = sys.stdout is None          # pythonw(창 없음)로 실행됨


def msgbox(text, error=True):
    """창 없이 실행 중일 때 사용자에게 알릴 방법 (Windows 메시지 상자)."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, (0x10 if error else 0x40) | 0x40000)


if HIDDEN:   # 콘솔이 없으면 출력을 로그 파일로 (1MB 넘으면 새로 시작)
    _log = common.DATA / "server.log"
    if _log.exists() and _log.stat().st_size > 1 << 20:
        _log.unlink()
    sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)
    print(f"\n----- {time.strftime('%Y-%m-%d %H:%M:%S')} 시작 -----")

try:
    import websockets
    from websockets.asyncio.server import serve
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    from wst import taskbar
    from wst import tls
    from wst.api import api_handler
    from wst.localterm import local_handler
    from wst.rawterm import raw_handler
    from wst.ftpconn import ftp_handler
    from wst.vncproxy import vnc_handler
    from wst.fsadapt import localfs_handler
    from wst import sftp as sftp_mod
    from wst.sftp import sftp_handler
    from wst.term import terminal_handler
    from wst.tunnels import manager
except ImportError as e:
    if HIDDEN:
        msgbox(f"필요한 패키지가 없습니다: {e.name}\n\n'실행(콘솔).bat'을 한 번 실행하면 자동으로 설치됩니다.")
    raise

if common.FROZEN:   # exe가 띄우는 크롬·mstsc·로컬 터미널에 PyInstaller의 DLL 경로·환경이 물려가지 않게
    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)

TOKEN = None  # main에서 설정
WS_PATHS = ("/ws", "/sftp", "/local", "/api", "/raw", "/vnc", "/ftp", "/localfs")


def _token_url(url, token):
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "t"]
    if token is not None:
        query.append(("t", token))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _mask_token(text):
    return re.sub(r'([?&]t=)[^&#\s\"\'<>]*', r'\1***', text)


class _TokenLogFilter(logging.Filter):
    def filter(self, record):
        record.msg = _mask_token(record.getMessage())
        record.args = ()
        return True


def _read_token():
    try:
        return (common.DATA / "token").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _write_token():
    path = common.DATA / "token"
    if TOKEN is None:
        path.unlink(missing_ok=True)
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(TOKEN)
    try:
        if os.name == "nt":
            import csv
            whoami = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe")
            identity = subprocess.check_output([whoami, "/user", "/fo", "csv", "/nh"],
                                               creationflags=common.NO_WINDOW).decode(errors="replace")
            sid = next(csv.reader(identity.splitlines()))[1]
            icacls = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "icacls.exe")
            subprocess.run([icacls, str(path), "/inheritance:r", "/grant:r", f"*{sid}:F"],
                           check=True, capture_output=True, creationflags=common.NO_WINDOW)
        else:
            path.chmod(0o600)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, StopIteration):
        logging.warning("토큰 파일 권한 제한 실패 (실행은 계속합니다)")


# ── HTTP (정적 파일) ──────────────────────────────────────────
def _resp(status, body=b"", ctype="text/plain; charset=utf-8", extra=()):
    st = HTTPStatus(status)
    headers = Headers([
        ("Content-Type", ctype),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "same-origin"),
        *extra,
    ])
    return Response(st.value, st.phrase, headers, body)


def _token_ok(query):
    if TOKEN is None:
        return True
    given = parse_qs(query).get("t", [""])[0]
    return hmac.compare_digest(given.encode("utf-8"), TOKEN.encode("utf-8"))


async def process_request(connection, request):
    hosts = request.headers.get_all("Host")
    port = connection.local_address[1]
    if len(hosts) != 1 or hosts[0].lower() not in (
            f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"):
        return _resp(421, b"misdirected request")
    host = hosts[0]
    url = urlsplit(request.path)
    path = url.path

    if path.startswith("/dl/"):                   # SFTP 행을 탐색기로 끌어 내려받기 (sftp.make_ticket이 만든 일회성 표)
        if not _token_ok(url.query):
            return _resp(403, b"forbidden")
        try:
            r = await asyncio.to_thread(sftp_mod.read_ticket, path.split("/")[2])
        except Exception as e:
            return _resp(500, str(e).encode())
        if not r:
            return _resp(404, b"expired")
        name, data = r
        return _resp(200, data, "application/octet-stream",
                     [("Content-Disposition", "attachment; filename*=UTF-8''" + quote(name))])

    if path in WS_PATHS:
        if not _token_ok(url.query):
            return _resp(403, b"forbidden")
        origin = request.headers.get("Origin")
        if origin != f"http://{host}":
            return _resp(403, b"bad origin")
        return None  # WebSocket 핸드셰이크 진행

    # replaceState 뒤 새로고침은 토큰 없는 HTML을 받고 sessionStorage로 WS 인증을 이어간다.
    if path == "/":
        path = "/index.html"
    target = (common.STATIC / path.lstrip("/")).resolve()
    if common.STATIC not in target.parents or not target.is_file():
        return _resp(404, b"not found")
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype.endswith("javascript"):
        ctype += "; charset=utf-8"
    return _resp(200, target.read_bytes(), ctype)


async def handler(ws):
    url = urlsplit(ws.request.path)
    if url.path == "/sftp":
        sess = common.SESSIONS.get(parse_qs(url.query).get("sid", [""])[0])
        if not sess:
            await ws.close(1008, "no session")
            return
        await sftp_handler(ws, sess)
    elif url.path == "/local":
        await local_handler(ws)
    elif url.path == "/raw":
        await raw_handler(ws)
    elif url.path == "/ftp":
        await ftp_handler(ws)
    elif url.path == "/vnc":
        await vnc_handler(ws)
    elif url.path == "/localfs":
        await localfs_handler(ws)
    elif url.path == "/api":
        await api_handler(ws)
    else:
        await terminal_handler(ws)


# ── 실행 ─────────────────────────────────────────────────────
def _check_websockets_version(version: str) -> str | None:
    match = re.match(r"^(\d+)\.(\d+)(.*)$", version)
    if match and (tuple(map(int, match.group(1, 2))) < (17, 4)
                  or (tuple(map(int, match.group(1, 2))) == (17, 4)
                      and re.search(r"(?:a|b|rc|dev)\d*", match.group(3)))):
        return (f"websockets {version}: 보안 업데이트가 필요합니다 (요구 버전: websockets>=17.4, "
                "GHSA-6m5v-9gmr-5665).")
    return None


def _find_chrome():
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            exe = Path(base) / "Google/Chrome/Application/chrome.exe"
            if exe.exists():
                return exe
    return None


def _open_browser(url):
    chrome = _find_chrome()
    if chrome:
        foreground.open_foreground(lambda: subprocess.Popen([str(chrome), f"--app={url}"]),
                                   match=foreground.browser_window)   # 주소창 없는 앱 창
    else:
        foreground.open_foreground(lambda: webbrowser.open(url), match=foreground.browser_window, reuse=True)


def _cleanup_legacy_ca(remove=False, gui=False):
    if not tls.legacy_present():
        return
    if not remove:
        if common.settings().get("legacyCaKeep"):
            return
        message = "이전 버전이 설치한 로컬 인증서(CA)가 남아 있습니다. 이제 쓰지 않으므로 제거를 권장합니다. 제거할까요?"
        if gui and os.name == "nt":
            import ctypes
            answer = ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x04 | 0x20 | 0x10000)
            if answer != 6:   # IDYES
                if answer == 7:   # IDNO
                    settings = common.settings()
                    settings["legacyCaKeep"] = True
                    common.save("settings", settings)
                return
        else:
            print("이전 버전의 로컬 인증서(CA)가 남아 있습니다. --remove-legacy-ca로 제거할 수 있습니다.")
            return
    result = tls.remove_legacy()
    print(f"이전 CA 정리: {result}")
    if result["error"] and gui:
        msgbox(f"이전 CA 제거 실패: {result['error']}")


def _who_has_port(port):
    """None = 비어 있음, ours = 이 프로그램, legacy = 이전 HTTPS 버전, other = 다른 프로그램."""
    try:
        socket.create_connection(("127.0.0.1", port), 1).close()
    except OSError:
        return None
    try:
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).read()
        return "ours" if APP_NAME.encode() in body else "other"
    except urllib.error.HTTPError:
        return "other"
    except Exception:
        pass
    try:
        body = urllib.request.urlopen(f"https://127.0.0.1:{port}/", timeout=3,
                                      context=ssl._create_unverified_context()).read()
        return "legacy" if APP_NAME.encode() in body else "other"
    except Exception:
        return "other"


async def _idle_exit(stop, grace=60):
    """브라우저 창이 모두 닫히고 터미널·터널도 없이 grace초가 지나면 종료 (창 없이 실행할 때)."""
    from wst import api
    idle = 0
    while not stop.is_set():
        await asyncio.sleep(5)
        busy = api._clients or common.SESSIONS or any(t.state != "off" for t in manager.tunnels.values())
        idle = 0 if busy else idle + 5
        if idle >= grace:
            print("브라우저 창이 닫혀 있어 자동 종료합니다.")
            stop.set()


async def main():
    global TOKEN
    ap = argparse.ArgumentParser(description="W.S.T")
    ap.add_argument("--host", default="127.0.0.1", help="바인딩 주소 (기본 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8022)
    ap.add_argument("--token", help="접속 토큰 (미지정이면 자동 생성)")
    ap.add_argument("--no-token", action="store_true", help="루프백에서만 토큰 없이 실행 (개발용)")
    ap.add_argument("--open", action="store_true", help="크롬 앱 창으로 열기")
    ap.add_argument("--trust", action="store_true", help="호환용, 무시")
    ap.add_argument("--no-tls", action="store_true", help="호환용, 무시")
    ap.add_argument("--remove-legacy-ca", action="store_true", help="이전 버전의 로컬 CA 신뢰 등록과 파일 제거")
    ap.add_argument("--auto-exit", action="store_true", help="브라우저 창을 모두 닫고 1분 지나면 종료 (터널 실행 중이면 유지)")
    ap.add_argument("--session", help="이 세션(이름 또는 id)을 바로 엽니다 (바탕화면 바로가기용, 이미 실행 중이면 새 창)")
    # exe를 더블클릭·시작프로그램으로 인수 없이 실행하면 실행.vbs와 같은 동작
    argv = sys.argv[1:]
    if common.FROZEN and argv and all(x.startswith("--session") or (i and argv[i - 1] == "--session") for i, x in enumerate(argv)):
        argv = ["--open", "--auto-exit"] + argv           # 바로가기: exe --session X 만 줘도 평소처럼 실행
    a = ap.parse_args(argv or (["--open", "--auto-exit"] if common.FROZEN else []))
    loopback = a.host in ("127.0.0.1", "localhost", "::1")
    if not loopback:
        ap.error("원격 모드는 v1.1에서 제거되었습니다. --host는 127.0.0.1·::1·localhost만 쓸 수 있습니다")
    from urllib.parse import quote as _q
    open_q = f"?open={_q(a.session)}" if a.session else ""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # cp949 콘솔에서 출력 오류 방지
    version_error = _check_websockets_version(websockets.__version__)
    if version_error:
        print(version_error)
        if HIDDEN:
            msgbox(version_error)
        raise SystemExit(1)

    # 이미 실행 중이면 새로 띄우지 않고 기존 서버의 창만 연다
    who = _who_has_port(a.port)
    if who == "ours":
        print("이미 실행 중 → 창만 엽니다.")
        if a.open or a.session:
            _open_browser(_token_url(f"http://127.0.0.1:{a.port}/{open_q}", _read_token()))
        return
    if who == "legacy":
        msg = "이전 버전 W.S.T가 실행 중입니다. ⚙설정 → 서버 종료로 끈 뒤 다시 실행하세요."
        print(msg)
        if HIDDEN:
            msgbox(msg)
        return
    if who == "other":
        msg = f"포트 {a.port}를 다른 프로그램이 쓰고 있습니다. --port 로 다른 포트를 지정하세요."
        print(msg)
        if HIDDEN:
            msgbox(msg)
        return

    # 브라우저가 연결을 끊을 때 Windows Proactor가 내는 무해한 ConnectionResetError 로그 숨김
    loop = asyncio.get_running_loop()

    def _quiet(lp, ctx):
        if isinstance(ctx.get("exception"), (ConnectionResetError, ConnectionAbortedError)):
            return
        lp.default_exception_handler(ctx)
    loop.set_exception_handler(_quiet)

    TOKEN = None if a.no_token else a.token or secrets.token_urlsafe(24)
    if a.no_token:
        logging.warning("토큰 없이 실행 중(개발용)")

    ws_logger = logging.getLogger("websockets.server")
    ws_logger.addFilter(_TokenLogFilter())
    token_file_owned = False
    try:
        async with serve(handler, a.host, a.port, process_request=process_request, ssl=None,
                         logger=ws_logger, max_size=4 << 20, ping_interval=20, close_timeout=2) as server:
            token_file_owned = True
            _write_token()
            await asyncio.to_thread(_cleanup_legacy_ca, a.remove_legacy_ca, HIDDEN or a.open)
            shown = f"[{a.host}]" if a.host == "::1" else a.host
            port = server.sockets[0].getsockname()[1]
            url = _token_url(f"http://{shown}:{port}/{open_q}", TOKEN)
            print(f"W.S.T 실행 중 → {_mask_token(url)}")
            print("종료: 화면의 ⚙설정 → 서버 종료" + ("" if HIDDEN else " 또는 Ctrl+C"))
            if loopback:
                from wst import hotkey
                common.hotkey_apply = lambda on: hotkey.start(lambda: _open_browser(url)) if on else hotkey.stop()
                common.hotkey_apply(bool(common.settings().get("globalHotkey")))
                if a.open or a.session:        # 창을 연 서버만: 시험 서버 등이 같은 창의 작업표시줄 ID를 덮어써 깜빡이던 문제 (11/4)
                    taskbar.start()   # 이 PC의 크롬 앱 창을 작업표시줄에서 이 프로그램으로 표시
            if a.open or a.session:
                _open_browser(url)
            stop = asyncio.Event()
            common.request_shutdown = lambda: loop.call_soon_threadsafe(stop.set)
            if a.auto_exit:
                asyncio.create_task(_idle_exit(stop))
            if loopback:
                from wst import api
                loop.run_in_executor(None, api.autostart_tunnels)      # "자동 시작" 터널
            try:
                await stop.wait()
            finally:
                (common.DATA / "token").unlink(missing_ok=True)
                manager.stop_all()
                # 크롬 앱 창을 닫은 뒤 남는 연결 때문에 서버 정리가 끝나지 않아 프로세스가 계속 남는 일이 있었음
                server.close()
                try:
                    await asyncio.wait_for(server.wait_closed(), 5)
                except TimeoutError:
                    print("연결 정리가 5초 안에 끝나지 않아 강제 종료")
                    sys.stdout.flush()
                    os._exit(0)
                print("종료됨")
    finally:
        if token_file_owned:
            (common.DATA / "token").unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        if HIDDEN:
            import traceback
            traceback.print_exc()
            msgbox(f"실행 중 오류로 종료됐습니다:\n{e}\n\n자세한 내용: data\\server.log")
        raise
