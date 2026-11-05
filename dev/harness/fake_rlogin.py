"""시험용 가짜 rlogind: 접속 정보(\\0로컬\\0원격\\0터미널\\0)를 받고 \\0 응답 후 입력을 그대로 되돌려 줌.
사용: python fake_rlogin.py <포트>
"""
import socket
import sys
import threading


def handle(c, addr):
    buf = b""
    while buf.count(b"\0") < 4:
        d = c.recv(1024)
        if not d:
            return
        buf += d
    _, local, remote, term = buf.split(b"\0")[:4]
    print("login", addr, local, remote, term, flush=True)
    c.sendall(b"\0" + b"rlogin ok " + remote + b"\r\n$ ")
    line = b""
    while True:
        d = c.recv(1024)
        if not d:
            break
        for ch in d:
            b = bytes([ch])
            if b == b"\r":
                c.sendall(b"\r\n" + line + b"\r\n$ ")
                line = b""
            else:
                line += b
                c.sendall(b)


s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen()
while True:
    c, a = s.accept()
    threading.Thread(target=handle, args=(c, a), daemon=True).start()
