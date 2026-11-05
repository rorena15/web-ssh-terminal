"""X11 포워딩: 원격 GUI 창을 이 PC의 X 서버(VcXsrv·X410·Xming)로.

브라우저 안에서는 X 서버를 돌릴 수 없으므로, 이 PC에서 TCP 6000(:0)에 떠 있는 X 서버로 채널을 잇는다.
X 서버가 없고 VcXsrv가 설치돼 있으면 -multiwindow -clipboard -auth 로 자동 실행한다.

인증(OpenSSH와 같은 방식): 원격에는 가짜 쿠키만 넘기고, 원격 X 클라이언트가 보낸 연결 첫 패킷의 쿠키가
가짜 쿠키와 맞을 때만 이 PC X 서버의 진짜 쿠키(data/x11/xauth)로 바꿔 넘긴다. 진짜 쿠키는 원격에 가지 않는다.
"""
import hmac
import os
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time

from wst import common
from wst import foreground

X_PORT = 6000                     # DISPLAY :0
CANDIDATES = [r"C:\Program Files\VcXsrv\vcxsrv.exe", r"C:\Program Files (x86)\VcXsrv\vcxsrv.exe",
              r"C:\Program Files (x86)\Xming\Xming.exe"]
AUTH_NAME = b"MIT-MAGIC-COOKIE-1"
AUTH_FILE = common.DATA / "x11" / "xauth"
_cookie_lock = threading.Lock()


def _listening():
    try:
        socket.create_connection(("127.0.0.1", X_PORT), 0.5).close()
        return True
    except OSError:
        return False


def _xauth_entry(cookie):
    """Xauthority 한 항목 (FamilyInternet 127.0.0.1, 디스플레이 0). X 서버는 -auth 파일의 주소는 보지 않고 쿠키만 등록."""
    f = lambda b: struct.pack(">H", len(b)) + b
    return struct.pack(">H", 0) + f(bytes([127, 0, 0, 1])) + f(b"0") + f(AUTH_NAME) + f(cookie)


def _read_cookie(raw):
    i = 0
    while i + 2 <= len(raw):
        i += 2                                    # family
        fields = []
        for _ in range(4):                        # address, number, name, data
            if i + 2 > len(raw):
                return None
            n = struct.unpack(">H", raw[i:i + 2])[0]
            fields.append(raw[i + 2:i + 2 + n])
            i += 2 + n
        if fields[2] == AUTH_NAME and len(fields[3]) == 16:
            return fields[3]
    return None


def real_cookie():
    """이 PC X 서버의 쿠키. 없으면 만들어 data/x11/xauth에 저장 (다음 실행 때 이미 떠 있는 VcXsrv와 맞도록 유지)."""
    with _cookie_lock:
        try:
            c = _read_cookie(AUTH_FILE.read_bytes())
            if c:
                return c
        except OSError:
            pass
        c = secrets.token_bytes(16)
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_bytes(_xauth_entry(c))
        return c


def ensure_xserver():
    """X 서버가 떠 있으면 None, 띄웠으면 None, 못 찾으면 안내 문구."""
    if _listening():
        return None
    exe = next((p for p in CANDIDATES if os.path.exists(p)), None) or shutil.which("vcxsrv.exe")
    if not exe or not common.LOCAL_MODE:
        return "X 서버가 없습니다 — VcXsrv(또는 X410·Xming)를 설치·실행하면 원격 GUI 창이 이 PC에 뜹니다."
    real_cookie()
    args = [exe, ":0", "-multiwindow", "-clipboard", "-auth", str(AUTH_FILE)]
    if "vcxsrv" in exe.lower():
        args.append("-wgl")
    foreground.open_foreground(lambda: subprocess.Popen(args, creationflags=common.NO_WINDOW))
    for _ in range(30):
        if _listening():
            return None
        time.sleep(0.2)
    return "X 서버를 실행했지만 응답이 없습니다."


def _pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except Exception:
        pass
    for x in (a, b):
        try:
            x.close()
        except Exception:
            pass


def _recv_exact(ch, n):
    buf = b""
    while len(buf) < n:
        d = ch.recv(n - len(buf))
        if not d:
            raise ConnectionError("closed")
        buf += d
    return buf


def _pad(n):
    return (4 - n % 4) % 4


def rewrite_setup(ch, fake):
    """X 연결 첫 패킷(setup request)을 읽어 가짜 쿠키를 확인하고 진짜 쿠키로 바꾼 패킷 반환. 안 맞으면 예외."""
    head = _recv_exact(ch, 12)
    order = {b"B": ">", b"l": "<"}.get(head[:1])
    if not order:
        raise ValueError("X11: 잘못된 바이트 순서")
    major, minor, n, d = struct.unpack(order + "HHHH", head[2:10])
    if n > 256 or d > 256:
        raise ValueError("X11: 인증 필드가 너무 김")
    name = _recv_exact(ch, n + _pad(n))[:n]
    data = _recv_exact(ch, d + _pad(d))[:d]
    if name != AUTH_NAME or not hmac.compare_digest(data, fake):
        raise PermissionError("X11: 쿠키 불일치")
    real = real_cookie()
    return (head[:2] + struct.pack(order + "HHHH", major, minor, len(AUTH_NAME), len(real)) + b"\0\0"
            + AUTH_NAME + b"\0" * _pad(len(AUTH_NAME)) + real + b"\0" * _pad(len(real)))


def _make_handler(fake):
    def handler(channel, origin):
        """paramiko request_x11 handler: 원격 X 클라이언트 연결 → (쿠키 확인·교체) → 이 PC의 X 서버."""
        def run():
            sock = None
            try:
                channel.settimeout(10)
                first = rewrite_setup(channel, fake)
                channel.settimeout(None)
                sock = socket.create_connection(("127.0.0.1", X_PORT), 5)
                sock.settimeout(None)
                sock.sendall(first)
            except Exception:
                channel.close()
                if sock:
                    sock.close()
                return
            threading.Thread(target=_pipe, args=(channel, sock), daemon=True).start()
            _pipe(sock, channel)
        threading.Thread(target=run, daemon=True).start()     # paramiko 수신 스레드를 막지 않게
    return handler


def open_shell(client, term, cols, rows):
    """X11 포워딩을 켠 셸 채널. 가짜 쿠키는 SSH 연결마다 하나 (같은 연결의 handler를 덮어써도 같은 값)."""
    tr = client.get_transport()
    chan = tr.open_session()
    chan.get_pty(term=term, width=cols, height=rows)
    chan.x11_error = None
    fake = getattr(tr, "_webssh_x11_cookie", None) or secrets.token_bytes(16)
    tr._webssh_x11_cookie = fake
    try:
        chan.request_x11(auth_protocol=AUTH_NAME.decode(), auth_cookie=fake.hex(),
                         single_connection=False, handler=_make_handler(fake))
    except Exception as e:                       # 서버가 X11Forwarding no 등 → 셸은 그대로 열고 알림만
        chan.x11_error = f"서버가 X11 포워딩을 거부했습니다 (sshd_config X11Forwarding 확인): {e}"
    chan.invoke_shell()
    return chan
