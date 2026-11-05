"""X11 쿠키 연동 시험: 가짜 sshd(2222)의 `xclient` → x11.py handler → 가짜 X 서버(127.0.0.1:6000).
가짜 X 서버는 WEBSSH_DATA/x11/xauth의 진짜 쿠키가 왔을 때만 1(성공)을 돌려준다.
실행: WEBSSH_DATA=<임시 폴더> python dev/harness/t_x11.py   (가짜 sshd 2222가 떠 있어야 함)"""
import os
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import paramiko
from wst import x11

got = []


def fake_x():
    lst = socket.socket()
    lst.bind(("127.0.0.1", x11.X_PORT))
    lst.listen(4)
    while True:
        c, _ = lst.accept()
        head = c.recv(12)
        n, d = struct.unpack("<HH", head[6:10])
        body = c.recv(x11._pad(n) + n + x11._pad(d) + d)
        name, data = body[:n], body[n + x11._pad(n):n + x11._pad(n) + d]
        got.append((name, data))
        c.sendall(b"\x01" if name == x11.AUTH_NAME and data == x11.real_cookie() else b"\x00")
        c.close()


threading.Thread(target=fake_x, daemon=True).start()
time.sleep(0.3)
cl = paramiko.SSHClient()
cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cl.connect("127.0.0.1", 2222, "test", "pw", look_for_keys=False, allow_agent=False)
ch = x11.open_shell(cl, "xterm", 80, 24)
fake = cl.get_transport()._webssh_x11_cookie


def run(cmd):
    ch.sendall(cmd.encode() + b"\r")
    buf, end = b"", time.time() + 8
    while time.time() < end and b"x11 " not in buf:
        buf += ch.recv(4096) if ch.recv_ready() else (time.sleep(0.05) or b"")
    time.sleep(0.1)
    return [l for l in buf.decode().splitlines() if l.startswith("x11 ")]


res = {m: run("xclient " + m) for m in ("good", "bad", "none")}
real = x11.real_cookie()
print("results:", res)
print("X server saw:", [(n.decode(), d.hex()[:8]) for n, d in got])
ok = (res["good"] == ["x11 reply 1"] and res["bad"] == ["x11 reply closed"] and res["none"] == ["x11 reply closed"]
      and len(got) == 1 and got[0][1] == real and fake != real)
print("fake != real:", fake != real)
print("PASS" if ok else "FAIL")
cl.close()
