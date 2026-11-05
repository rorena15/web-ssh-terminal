"""테스트용 간이 FTP 서버 (user test / pw). python fake_ftpd.py <port> <root> [mlsd|list]"""
import os
import socket
import socketserver
import sys
import time

PORT, ROOT = int(sys.argv[1]), os.path.abspath(sys.argv[2])
MODE = sys.argv[3] if len(sys.argv) > 3 else "mlsd"


class H(socketserver.StreamRequestHandler):
    def send(self, s):
        self.wfile.write((s + "\r\n").encode("utf-8"))

    def real(self, p):
        p = p if p.startswith("/") else (self.cwd.rstrip("/") + "/" + p)
        p = os.path.normpath(p).replace("\\", "/")
        return os.path.join(ROOT, p.lstrip("/")), p

    def data(self):
        c, _ = self.pasv.accept()
        self.pasv.close()
        return c

    def handle(self):
        self.cwd, self.pasv, self.rn = "/", None, None
        self.send("220 fake ftpd")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            line = line.decode("utf-8", "surrogateescape").rstrip("\r\n")
            cmd, _, arg = line.partition(" ")
            cmd = cmd.upper()
            try:
                self.do(cmd, arg)
            except FileNotFoundError:
                self.send("550 No such file")
            except Exception as e:
                self.send(f"550 {e}")
            if cmd == "QUIT":
                return

    def do(self, cmd, arg):
        if cmd == "USER":
            self.send("331 pw")
        elif cmd == "PASS":
            self.send("230 ok" if arg == "pw" else "530 Login incorrect")
        elif cmd == "FEAT":
            self.wfile.write(b"211-Features:\r\n" + (b" MLST type*;size*;modify*;unix.mode*;\r\n" if MODE == "mlsd" else b"") + b" UTF8\r\n211 End\r\n")
        elif cmd in ("OPTS", "TYPE"):
            self.send("200 ok")
        elif cmd == "PWD":
            self.send(f'257 "{self.cwd}"')
        elif cmd == "CWD":
            r, p = self.real(arg)
            if not os.path.isdir(r):
                raise FileNotFoundError
            self.cwd = p
            self.send("250 ok")
        elif cmd == "PASV":
            self.pasv = socket.socket()
            self.pasv.bind(("127.0.0.1", 0))
            self.pasv.listen(1)
            port = self.pasv.getsockname()[1]
            self.send(f"227 Entering Passive Mode (127,0,0,1,{port >> 8},{port & 255})")
        elif cmd in ("MLSD", "LIST"):
            arg = " ".join(a for a in arg.split() if not a.startswith("-"))
            r, _ = self.real(arg or ".")
            self.send("150 here")
            c = self.data()
            for n in os.listdir(r):
                s = os.stat(os.path.join(r, n))
                isd = os.path.isdir(os.path.join(r, n))
                if cmd == "MLSD":
                    t = time.strftime("%Y%m%d%H%M%S", time.gmtime(s.st_mtime))
                    c.sendall(f"type={'dir' if isd else 'file'};size={s.st_size};modify={t};unix.mode=0{'755' if isd else '644'}; {n}\r\n".encode())
                else:
                    t = time.strftime("%b %d %H:%M", time.localtime(s.st_mtime))
                    c.sendall(f"{'d' if isd else '-'}rw-r--r-- 1 test grp {s.st_size} {t} {n}\r\n".encode())
            c.close()
            self.send("226 done")
        elif cmd == "MLST":
            r, p = self.real(arg)
            s = os.stat(r)
            t = time.strftime("%Y%m%d%H%M%S", time.gmtime(s.st_mtime))
            self.wfile.write(f"250-x\r\n type={'dir' if os.path.isdir(r) else 'file'};size={s.st_size};modify={t}; {p}\r\n250 End\r\n".encode())
        elif cmd == "SIZE":
            r, _ = self.real(arg)
            if os.path.isdir(r):
                raise Exception("not a file")
            self.send(f"213 {os.path.getsize(r)}")
        elif cmd == "MDTM":
            r, _ = self.real(arg)
            self.send("213 " + time.strftime("%Y%m%d%H%M%S", time.gmtime(os.stat(r).st_mtime)))
        elif cmd == "RETR":
            r, _ = self.real(arg)
            data = open(r, "rb").read()
            self.send("150 here")
            c = self.data()
            c.sendall(data)
            c.close()
            self.send("226 done")
        elif cmd == "STOR":
            r, _ = self.real(arg)
            self.send("150 go")
            c = self.data()
            with open(r, "wb") as f:
                while d := c.recv(65536):
                    f.write(d)
            c.close()
            self.send("226 done")
        elif cmd == "MKD":
            os.mkdir(self.real(arg)[0])
            self.send("257 made")
        elif cmd == "RMD":
            os.rmdir(self.real(arg)[0])
            self.send("250 ok")
        elif cmd == "DELE":
            os.remove(self.real(arg)[0])
            self.send("250 ok")
        elif cmd == "RNFR":
            self.rn = self.real(arg)[0]
            self.send("350 ok")
        elif cmd == "RNTO":
            os.rename(self.rn, self.real(arg)[0])
            self.send("250 ok")
        elif cmd == "SITE":
            self.send("200 ok")
        elif cmd == "QUIT":
            self.send("221 bye")
        else:
            self.send("502 not implemented")


class S(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


S(("127.0.0.1", PORT), H).serve_forever()
