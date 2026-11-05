"""테스트용 가짜 VNC(RFB 3.8, 인증 없음) 서버: 64x48 화면, 업데이트 요청마다 단색 사각형. python fake_vnc.py <port>"""
import socket
import struct
import sys
import threading

W, H = 64, 48


def handle(c):
    try:
        c.sendall(b"RFB 003.008\n")
        c.recv(12)
        c.sendall(b"\x01\x01")                         # 보안 유형 1개: None
        c.recv(1)
        c.sendall(struct.pack(">I", 0))                # SecurityResult OK
        c.recv(1)                                      # ClientInit
        pf = struct.pack(">BBBBHHHBBBxxx", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        name = b"fake-vnc"
        c.sendall(struct.pack(">HH", W, H) + pf + struct.pack(">I", len(name)) + name)
        n = 0
        while True:
            t = c.recv(1)
            if not t:
                return
            kind = t[0]
            if kind == 0:
                c.recv(19)                             # SetPixelFormat
            elif kind == 2:
                cnt = struct.unpack(">xH", c.recv(3))[0]
                c.recv(4 * cnt)                        # SetEncodings
            elif kind == 3:
                c.recv(9)                              # FramebufferUpdateRequest
                n += 1
                col = bytes([(n * 40) % 256, 120, 200, 0])
                c.sendall(struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", 0, 0, W, H, 0) + col * (W * H))
            elif kind == 4:
                c.recv(7)                              # KeyEvent
            elif kind == 5:
                c.recv(5)                              # PointerEvent
            elif kind == 6:
                ln = struct.unpack(">xxxI", c.recv(7))[0]
                c.recv(ln)
            else:
                return
    except OSError:
        pass
    finally:
        c.close()


s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen(4)
while True:
    c, _ = s.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()
