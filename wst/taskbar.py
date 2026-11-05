"""작업표시줄: 크롬 앱 창을 이 프로그램 창으로 보이게 한다 (Windows).

크롬 --app 창은 크롬 프로세스의 창이라 작업표시줄에 고정하면 chrome.exe와 크롬 아이콘이 고정된다.
창의 속성 저장소에 AppUserModelID와 다시 실행할 명령·아이콘을 넣으면, 크롬과 따로 묶이고
고정했을 때 이 exe와 아이콘이 고정된다. 크롬이 창을 새로 만들 수 있어 주기적으로 확인한다.
"""
import ctypes
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from wst import common

APP_ID = "rorena15.WST"            # 작업 표시줄 그룹·고정 ID (11/4 변경, 옛 고정은 다시 고정 필요)
TITLE = "W.S.T"                  # index.html <title>, 탭을 고르면 "<탭> — W.S.T"
_FMTID = uuid.UUID("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")   # PKEY_AppUserModel_*
PID_RELAUNCH_CMD, PID_RELAUNCH_ICON, PID_RELAUNCH_NAME, PID_ID = 2, 3, 4, 5
VT_LPWSTR = 31


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, u):
        return cls.from_buffer_copy(u.bytes_le)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                ("val", ctypes.c_void_p), ("pad", ctypes.c_void_p)]


IID_IPropertyStore = GUID.of(uuid.UUID("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"))


def _launch():
    """고정 아이콘을 눌렀을 때 실행할 명령과 아이콘."""
    if common.FROZEN:
        return f'"{sys.executable}"', f"{sys.executable},0"
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return (f'"{pyw if pyw.exists() else sys.executable}" "{common.BASE / "server.py"}" --open --trust --auto-exit',
            str(common.BASE / "build" / "webssh.ico"))


def _store(hwnd):
    p = ctypes.c_void_p()
    if ctypes.windll.shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(IID_IPropertyStore), ctypes.byref(p)):
        return None
    return p


def _call(store, index, restype, *argtypes):
    vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])


def _key(pid):
    return PROPERTYKEY(GUID.of(_FMTID), pid)


def get_app_id(hwnd):
    store = _store(hwnd)
    if not store:
        return None
    try:
        pv = PROPVARIANT()
        _call(store, 5, ctypes.HRESULT, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(
            store, ctypes.byref(_key(PID_ID)), ctypes.byref(pv))          # GetValue
        val = ctypes.wstring_at(pv.val) if pv.vt == VT_LPWSTR and pv.val else None
        ctypes.windll.ole32.PropVariantClear(ctypes.byref(pv))
        return val
    finally:
        _call(store, 2, wintypes.ULONG)(store)                              # Release


def tag(hwnd):
    store = _store(hwnd)
    if not store:
        return False
    cmd, icon = _launch()
    set_value = _call(store, 6, ctypes.HRESULT, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))
    try:
        # 다시 실행 정보를 먼저, ID를 마지막에 (ID가 바뀔 때 셸이 다시 실행 정보를 읽음)
        for pid, text in ((PID_RELAUNCH_CMD, cmd), (PID_RELAUNCH_ICON, icon),
                          (PID_RELAUNCH_NAME, TITLE), (PID_ID, APP_ID)):
            buf = ctypes.create_unicode_buffer(text)
            pv = PROPVARIANT(vt=VT_LPWSTR, val=ctypes.cast(buf, ctypes.c_void_p).value)
            set_value(store, ctypes.byref(_key(pid)), ctypes.byref(pv))
        _call(store, 7, ctypes.HRESULT)(store)                              # Commit
        return True
    except OSError:
        return False
    finally:
        _call(store, 2, wintypes.ULONG)(store)


def _our_windows():
    """크롬 앱 창 중 이 프로그램 화면인 것 (일반 크롬 탭은 제목 끝에 ' - Chrome'이 붙어 제외됨)."""
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if u.IsWindowVisible(hwnd):
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(hwnd, cls, 64)
            if cls.value == "Chrome_WidgetWin_1":
                n = u.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, title, n + 1)
                if title.value in (TITLE, "웹 SSH 터미널") or title.value.endswith((" — W.S.T", " — 웹 SSH")):
                    found.append(hwnd)
        return True
    u.EnumWindows(cb, 0)
    return found


def _watch():
    while True:
        try:
            for hwnd in _our_windows():
                if get_app_id(hwnd) != APP_ID:
                    tag(hwnd)
        except Exception as e:   # 작업표시줄 표시는 부가 기능이라 서버를 멈추지 않음
            print(f"작업표시줄 설정 실패: {e}")
            return
        time.sleep(1)


def start():
    if sys.platform == "win32":
        threading.Thread(target=_watch, daemon=True, name="taskbar").start()
