"""2026-11-13 RDP 실행 방식 시험 (Claude 검증).
- mstsc 인수: 기본은 /v: 명령줄, 클립보드 끔·드라이브 연결만 .rdp 파일, 인수 주입 거부
- 실제 mstsc: /v: 실행 시 Windows의 'RDP 파일' 보안 확인 창이 뜨지 않음 (대상 127.0.0.1:1, 접속 안 됨)
실행: WEBSSH_DATA=<임시 폴더> python dev/harness/t_rdp_launch.py [--no-real]"""
import ctypes, os, subprocess, sys, time
from ctypes import wintypes as w
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wst import api, foreground

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


M = str(api.MSTSC)
a = api._mstsc_args
check("기본(전체 화면)", a({"host": "10.0.0.5"}, "10.0.0.5:3389") == [M, "/v:10.0.0.5:3389", "/f"])
check("전체 화면 + 다중 모니터", a({"host": "h", "multimon": True}, "h:3389") == [M, "/v:h:3389", "/f", "/multimon"])
check("창 크기 + 관리 콘솔", a({"host": "h", "screen": "1280x720", "admin": True}, "h:3389") == [M, "/v:h:3389", "/w:1280", "/h:720", "/admin"])
check("창 모드에서는 다중 모니터 무시", "/multimon" not in a({"host": "h", "screen": "1024x768", "multimon": True}, "h:3389"))
check("게이트웨이 주소", a({"host": "10.0.0.5"}, "127.77.1.2:34000")[1] == "/v:127.77.1.2:34000")
check("IPv6 주소", a({"host": "::1"}, "[::1]:3389")[1] == "/v:[::1]:3389")
for label, s in (("클립보드 끔", {"host": "h", "name": "t_clip", "clipboard": False}),
                 ("드라이브 연결", {"host": "h", "name": "t_drv", "drives": True})):
    r = a(s, "h:3389")
    check(f"{label} → .rdp 파일", len(r) == 2 and r[1].endswith(".rdp") and Path(r[1]).is_file(), r[1])
for bad in ("h:3389 /p", 'h"x', "h:3389\t", "h;calc", "/v:h"):
    check(f"주소 주입 거부 {bad!r}", raises(lambda: a({"host": "h"}, bad)))
check("호스트 제어문자 거부", raises(lambda: a({"host": "h\r\nx"}, "h:3389")))
check("사용자 이름 제어문자 거부", raises(lambda: a({"host": "h", "username": "u\nfull address:s:evil"}, "h:3389")))
check("잘못된 창 크기 거부", raises(lambda: a({"host": "h", "screen": "axb"}, "h:3389")))

if "--no-real" not in sys.argv:
    u = ctypes.WinDLL("user32")
    CB = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    def texts(h):
        out = []
        def cb(c, _):
            n = u.SendMessageW(c, 0x000E, 0, 0) + 1
            b = ctypes.create_unicode_buffer(n); u.SendMessageW(c, 0x000D, n, b)
            if b.value.strip():
                out.append(b.value)
            return True
        u.EnumChildWindows(h, CB(cb), 0)
        return " | ".join(out)

    p = foreground.open_foreground(lambda: subprocess.Popen(a({"host": "127.0.0.1", "screen": "1024x768"}, "127.0.0.1:1")),
                                   timeout=20, flash=True)
    t0, seen = time.monotonic(), ""
    while time.monotonic() - t0 < 20 and not seen:
        for h, (pid, c, t) in foreground._windows(u).items():
            if pid == p.pid and c == "#32770":
                time.sleep(0.3)
                seen = texts(h)
        time.sleep(0.1)
    p.terminate()
    check("실제 mstsc /v: 에 RDP 파일 경고 없음", bool(seen) and "RDP 파일" not in seen and "RDP" not in seen.split("|")[0], seen)

print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
