"""가짜 텔넷 서버: NAWS·ECHO 협상 후 줄 단위 에코. python fake_telnet.py <port>"""
import socket, sys, threading
def handle(c):
    c.sendall(bytes([255,253,31, 255,251,1, 255,251,3]) + b"fake telnet\r\nlogin: ")
    buf = b""
    while True:
        d = c.recv(4096)
        if not d: return
        i = 0
        while i < len(d):
            b = d[i]
            if b == 255:                       # IAC 명령 건너뛰기
                if d[i+1] == 250:
                    j = d.index(bytes([255,240]), i); 
                    if d[i+2] == 31: c.sendall(f"[naws {int.from_bytes(d[i+3:i+5],'big')}x{int.from_bytes(d[i+5:i+7],'big')}]\r\n".encode())
                    i = j + 2; continue
                i += 3; continue
            ch = bytes([b]); i += 1
            if ch in (b"\r", b"\n"):
                if buf == b"quit": c.sendall(b"\r\nbye\r\n"); c.close(); return
                if buf: c.sendall(b"\r\nyou said: " + buf + b"\r\n> ")
                buf = b""
            else:
                buf += ch; c.sendall(ch)
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", int(sys.argv[1]))); s.listen(5)
while True:
    c, _ = s.accept(); threading.Thread(target=handle, args=(c,), daemon=True).start()
