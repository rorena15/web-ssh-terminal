"""외부 창 실행과 Windows 포그라운드 전환 (실패해도 실행 결과는 유지)."""
import ctypes
import os
import threading
import time
from ctypes import wintypes
from functools import lru_cache


@lru_cache(maxsize=1)
def _user32():
    if os.name != "nt" or not hasattr(ctypes, "windll"):
        return None
    u = ctypes.WinDLL("user32", use_last_error=True)
    signatures = {
        "GetForegroundWindow": (wintypes.HWND, []),
        "IsWindowVisible": (wintypes.BOOL, [wintypes.HWND]),
        "IsIconic": (wintypes.BOOL, [wintypes.HWND]),
        "GetWindowTextLengthW": (ctypes.c_int, [wintypes.HWND]),
        "GetWindowTextW": (ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
        "GetClassNameW": (ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
        "GetWindowThreadProcessId": (wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
        "ShowWindowAsync": (wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
        "SetForegroundWindow": (wintypes.BOOL, [wintypes.HWND]),
        "AttachThreadInput": (wintypes.BOOL, [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]),
        "GetAsyncKeyState": (ctypes.c_short, [ctypes.c_int]),
        "keybd_event": (None, [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]),
    }
    for name, (restype, argtypes) in signatures.items():
        fn = getattr(u, name)
        fn.restype, fn.argtypes = restype, argtypes
    return u


def _windows(u):
    found = {}
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback
    def collect(hwnd, _):
        if u.IsWindowVisible(hwnd) or u.IsIconic(hwnd):
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            cls = ctypes.create_unicode_buffer(256)
            title = ctypes.create_unicode_buffer(u.GetWindowTextLengthW(hwnd) + 1)
            u.GetClassNameW(hwnd, cls, len(cls))
            u.GetWindowTextW(hwnd, title, len(title))
            found[hwnd] = (pid.value, cls.value, title.value)
        return True

    u.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    u.EnumWindows.restype = wintypes.BOOL
    if not u.EnumWindows(collect, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return found


def bring_to_front(hwnd):
    """최소화 복원 후 전환. 성공 여부를 반환하며 부가 기능 오류는 삼킨다."""
    try:
        u = _user32()
        if u is None:
            return False
        if u.IsIconic(hwnd):
            u.ShowWindowAsync(hwnd, 9)                   # SW_RESTORE
        u.SetForegroundWindow(hwnd)
        if u.GetForegroundWindow() == hwnd:
            return True
        current = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = []
        try:
            for window in (u.GetForegroundWindow(), hwnd):
                tid = u.GetWindowThreadProcessId(window, None) if window else 0
                if tid and tid != current and tid not in attached and u.AttachThreadInput(current, tid, True):
                    attached.append(tid)
            u.SetForegroundWindow(hwnd)
        finally:
            for tid in reversed(attached):
                u.AttachThreadInput(current, tid, False)
        if u.GetForegroundWindow() != hwnd:
            # 사용자가 누르고 있는 Alt는 건드리지 않고, 합성 키는 반드시 뗀다.
            alt_down = bool(u.GetAsyncKeyState(0x12) & 0x8000)
            try:
                if not alt_down:
                    u.keybd_event(0x12, 0, 0, 0)
                u.SetForegroundWindow(hwnd)
            finally:
                if not alt_down:
                    u.keybd_event(0x12, 0, 2, 0)
        return u.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _watch(u, before, result, match, reuse):
    try:
        pid = getattr(result, "pid", None)
        started = time.monotonic()
        deadline = started + 3
        while time.monotonic() < deadline:
            windows = _windows(u)
            owned, fresh, existing = [], [], []
            for hwnd, (wpid, cls, title) in windows.items():
                if pid and wpid == pid:
                    owned.append(hwnd)
                elif match and match(cls, title):
                    if hwnd not in before or before[hwnd] != windows[hwnd]:
                        fresh.append(hwnd)
                    elif reuse:
                        existing.append(hwnd)
            # PID를 재사용하는 셸·브라우저는 클래스와 제목으로 제한한다.
            candidates = owned or fresh
            if not candidates and len(existing) == 1 and time.monotonic() - started >= 0.5:
                candidates = existing                     # 새 창이 나타날 시간을 먼저 준다
            if candidates and bring_to_front(candidates[0]):
                return
            time.sleep(0.1)
    except Exception:
        pass


def open_foreground(launch, *, match=None, reuse=False):
    """launch()를 한 번 실행하고 원래 결과를 반환. 창 찾기는 최대 3초간 별도 스레드에서.

    match(class_name, title)는 셸/브라우저처럼 기존 프로세스에 위임하는 실행용.
    reuse=True이면 제목이 맞는 기존 창이 하나뿐일 때 그 창도 앞으로 가져온다.
    """
    u, before = None, {}
    try:
        u = _user32()
        if u is not None:
            before = _windows(u)
    except Exception:
        u = None
    result = launch()                                    # 실행 자체의 예외·반환값은 기존대로
    if u is not None:
        try:
            threading.Thread(target=_watch, args=(u, before, result, match, reuse),
                             daemon=True, name="foreground").start()
        except Exception:
            pass
    return result


def open_folder(path):
    """Explorer는 기존 프로세스에 위임하므로 폴더명/전체 경로 제목도 비교한다."""
    path = os.path.abspath(path)
    names = {os.path.basename(os.path.normpath(path)).casefold(), path.casefold()}
    return open_foreground(lambda: os.startfile(path),
                           match=lambda cls, title: cls in ("CabinetWClass", "ExploreWClass")
                           and title.casefold() in names, reuse=True)


def browser_window(cls, title):
    return cls in ("Chrome_WidgetWin_1", "MozillaWindowClass") and (
        title.startswith("W.S.T") or title.endswith(" — W.S.T")
        or " — W.S.T - " in title or " — W.S.T — " in title
        or title.startswith("웹 SSH 터미널") or title.endswith("웹 SSH")
        or " — 웹 SSH - " in title or " — 웹 SSH — " in title)
