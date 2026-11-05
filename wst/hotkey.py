"""전역 단축키 (Ctrl+Alt+M): 어디서든 누르면 앱 창을 앞으로 / 이미 앞이면 최소화.
창이 없으면 새로 연다. 설정의 globalHotkey가 켜져 있을 때만 등록 (다른 프로그램과 겹칠 수 있어서).
"""
import ctypes
import threading
from ctypes import wintypes

from wst.foreground import bring_to_front

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_M = 0x4D
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
_thread = None
_tid = None


def _app_windows():
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if not u.IsWindowVisible(h) and not u.IsIconic(h):
            return True
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, cls, 64)
        if cls.value != "Chrome_WidgetWin_1":
            return True
        n = u.GetWindowTextLengthW(h)
        t = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, t, n + 1)
        if t.value.endswith((" — W.S.T", "웹 SSH")) or t.value in ("W.S.T", "웹 SSH 터미널"):
            found.append(h)
        return True
    u.EnumWindows(cb, 0)
    return found


def _toggle(open_new):
    u = ctypes.windll.user32
    wins = _app_windows()
    if not wins:
        open_new()
        return
    h = wins[0]
    if u.GetForegroundWindow() == h and not u.IsIconic(h):
        u.ShowWindow(h, 6)                              # SW_MINIMIZE
        return
    bring_to_front(h)


def start(open_new):
    """open_new: 창이 없을 때 새 창을 여는 함수."""
    global _thread
    if _thread:
        return

    def loop():
        global _tid
        u = ctypes.windll.user32
        _tid = ctypes.windll.kernel32.GetCurrentThreadId()
        if not u.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_M):
            print("전역 단축키 Ctrl+Alt+M 등록 실패 (다른 프로그램이 사용 중)")
            global _thread
            _thread = None
            return
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    _toggle(open_new)
                except Exception as e:
                    print("단축키 처리 오류:", e)
        u.UnregisterHotKey(None, 1)

    _thread = threading.Thread(target=loop, daemon=True)
    _thread.start()


def stop():
    global _thread
    if _thread and _tid:
        ctypes.windll.user32.PostThreadMessageW(_tid, WM_QUIT, 0, 0)
    _thread = None
