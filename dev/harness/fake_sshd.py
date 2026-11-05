"""테스트용 가짜 SSH 서버: 비밀번호 pw, 간단한 셸(echo/pwd/cd/exit/에코), exec(모니터링 흉내), SFTP(임시 폴더), direct-tcpip.
X11: x11-req의 가짜 쿠키를 기억, 셸에서 `xclient good|bad|none` → X 클라이언트처럼 x11 채널을 열어 setup 패킷을 보내고 응답 첫 바이트 출력.
python fake_sshd.py <port> <sftp_root> [--deny-file-access] [--demo]"""
import os
import posixpath
import socket
import sys
import threading
import time

import paramiko
from paramiko import SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface, SFTP_OK, SFTP_NO_SUCH_FILE

PORT = int(sys.argv[1])
ROOT = os.path.abspath(sys.argv[2])
DENY_FILE_ACCESS = "--deny-file-access" in sys.argv[3:]
DEMO = "--demo" in sys.argv[3:]
_KF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hostkey")
if not os.path.exists(_KF):
    paramiko.RSAKey.generate(2048).write_private_key_file(_KF)
HOSTKEY = paramiko.RSAKey.from_private_key_file(_KF)

MON = ("cpu  100 0 100 800 0 0 0 0 0 0\n@@\nMemTotal: 8000000 kB\nMemAvailable: 6000000 kB\n@@\n"
       "/dev/sda1 100000 45000 55000 45% /\n@@\nInter-|\n face |\n  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n@@\n"
       "0.10 0.20 0.30 1/100 1\n@@\n12345.6 0\n")

# --demo에서만 사용. 실제 명령 실행이나 외부 서버 접속 없이 정해진 더미 출력.
DEMO_OUTPUT = {
    "ls": "app  app.conf  backups  deploy.sh  README.txt  reports\n",
    "ls -la": (
        "total 32\n"
        "drwxr-xr-x  5 test test 4096 Nov  5 09:00 .\n"
        "drwxr-xr-x  3 test test 4096 Nov  5 08:00 ..\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:30 app\n"
        "-rw-r--r--  1 test test   35 Nov  5 08:30 app.conf\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:00 backups\n"
        "-rwxr-xr-x  1 test test   42 Nov  5 08:30 deploy.sh\n"
        "-rw-r--r--  1 test test   46 Nov  5 08:00 README.txt\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 09:00 reports\n"),
    "ls -la --color": (
        "total 88\n"
        "drwxr-xr-x 12 test test 4096 Nov  5 09:00 \x1b[1;34m.\x1b[0m\n"
        "drwxr-xr-x  3 test test 4096 Nov  5 08:00 \x1b[1;34m..\x1b[0m\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:30 \x1b[1;34mapp\x1b[0m\n"
        "-rw-r--r--  1 test test   35 Nov  5 08:30 app.conf\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:00 \x1b[1;34mbackups\x1b[0m\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:20 \x1b[1;34mbin\x1b[0m\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:20 \x1b[1;34mconfig\x1b[0m\n"
        "-rwxr-xr-x  1 test test  142 Nov  5 08:30 \x1b[32mdeploy.sh\x1b[0m\n"
        "-rw-r--r--  1 test test  256 Nov  5 08:15 Dockerfile\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:20 \x1b[1;34mlogs\x1b[0m\n"
        "-rw-r--r--  1 test test  512 Nov  5 08:15 nginx.conf\n"
        "-rw-r--r--  1 test test 1024 Nov  5 08:15 package.json\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:20 \x1b[1;34mpublic\x1b[0m\n"
        "-rw-r--r--  1 test test   46 Nov  5 08:00 README.txt\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 09:00 \x1b[1;34mreports\x1b[0m\n"
        "-rwxr-xr-x  1 test test  180 Nov  5 08:30 \x1b[32mrestart.sh\x1b[0m\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:20 \x1b[1;34mscripts\x1b[0m\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:20 \x1b[1;34mtests\x1b[0m\n"
        "drwxr-xr-x  2 test test 4096 Nov  5 08:20 \x1b[1;34mtmp\x1b[0m\n"),
    "uptime": " 09:41:00 up 12 days,  3:24,  2 users,  load average: 0.18, 0.24, 0.21\n",
    "df -h": ("Filesystem      Size  Used Avail Use% Mounted on\n"
              "/dev/sda1        80G   28G   52G  35% /\n"
              "tmpfs            4G   16M    4G   1% /run\n"
              "devtmpfs         4G     0    4G   0% /dev\n"
              "tmpfs            4G   32M    4G   1% /dev/shm\n"
              "tmpfs          5.0M     0  5.0M   0% /run/lock\n"
              "/dev/sda2       1.0G  180M  844M  18% /boot\n"
              "/dev/sda15      256M   12M  244M   5% /boot/efi\n"
              "/dev/sdb1       200G   64G  136G  32% /srv/app\n"
              "/dev/sdc1       100G   12G   88G  12% /var/log\n"
              "/dev/sdd1       500G  120G  380G  24% /backups\n"
              "tmpfs            4G   24M    4G   1% /tmp\n"
              "tmpfs          800M   12K  800M   1% /run/user/1000\n"),
    "systemctl status nginx": (
        "nginx.service - Web server\n"
        "     Loaded: loaded; enabled\n"
        "     Active: \x1b[32mactive (running)\x1b[0m\n"
        "      Since: Thu 2026-11-05 08:30:00 UTC\n"
        "       Docs: man:nginx(8)\n"
        "    Process: 1418 ExecStartPre=nginx -t (status=0/SUCCESS)\n"
        "   Main PID: 1420 (nginx)\n"
        "      Tasks: 3\n"
        "     Memory: 18.4M\n"
        "     Status: ready to serve requests on port 8080\n"
        "     CGroup: /system.slice/nginx.service\n"
        "             1420 nginx: master process\n"
        "             1421 nginx: worker process\n"
        "             1422 nginx: worker process\n"
        "Nov 05 08:30:00 web-01 systemd: Starting nginx...\n"
        "Nov 05 08:30:00 web-01 nginx: configuration test success\n"
        "Nov 05 08:30:00 web-01 systemd: Started nginx.\n"),
    "tail -n 20 /var/log/app.log": (
        "2026-11-05 09:40:01 INFO app worker started\n"
        "2026-11-05 09:40:02 OK config loaded\n"
        "2026-11-05 09:40:03 INFO listen 192.0.2.12:8080\n"
        "2026-11-05 09:40:04 INFO peer 198.51.100.24\n"
        "2026-11-05 09:40:05 OK GET /health 200\n"
        "2026-11-05 09:40:06 INFO GET /api/users 200\n"
        "2026-11-05 09:40:07 OK cache warmup success\n"
        "2026-11-05 09:40:08 INFO peer 203.0.113.42\n"
        "2026-11-05 09:40:09 warning queue depth=48\n"
        "2026-11-05 09:40:10 INFO worker pool scaled\n"
        "2026-11-05 09:40:11 OK GET /assets/app.css 200\n"
        "2026-11-05 09:40:12 error upstream reset\n"
        "2026-11-05 09:40:13 INFO retry 192.0.2.21\n"
        "2026-11-05 09:40:14 timeout upstream after 3s\n"
        "2026-11-05 09:40:15 warning retry attempt=2\n"
        "2026-11-05 09:40:16 OK upstream reconnected\n"
        "2026-11-05 09:40:17 INFO GET /api/reports 200\n"
        "2026-11-05 09:40:18 OK request success in 24ms\n"
        "2026-11-05 09:40:19 INFO active connections=32\n"
        "2026-11-05 09:40:20 OK health check success\n"),
}


def demo_monitor():
    tick = int(time.monotonic() * 100)
    return (f"cpu  {tick * 12} 0 {tick * 6} {tick * 82} 0 0 0 0 0 0\n@@\n"
            "MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\n@@\n"
            "/dev/sda1 83886080 29360128 54525952 35% /\n@@\nInter-|\n face |\n"
            f" eth0: {tick * 240} 0 0 0 0 0 0 0 {tick * 80} 0 0 0 0 0 0 0\n@@\n"
            "0.18 0.24 0.21 2/180 1420\n@@\n1049040.0 0\n")


class Server(paramiko.ServerInterface):
    def check_auth_password(self, u, p):
        return paramiko.AUTH_SUCCESSFUL if p == "pw" else paramiko.AUTH_FAILED

    def get_allowed_auths(self, u):
        return "password"

    def check_channel_request(self, kind, cid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_pty_request(self, *a):
        return True

    def check_channel_shell_request(self, ch):
        threading.Thread(target=shell, args=(ch,), daemon=True).start()
        return True

    def check_channel_exec_request(self, ch, cmd):
        threading.Thread(target=execute, args=(ch, cmd.decode("utf-8", "replace")), daemon=True).start()
        return True

    def check_channel_window_change_request(self, *a):
        return True

    def check_channel_direct_tcpip_request(self, cid, origin, dest):
        self.dt = getattr(self, "dt", {}); self.dt[cid] = dest
        return paramiko.OPEN_SUCCEEDED

    def check_port_forward_request(self, addr, port):
        port = port or 40000
        lst = socket.socket(); lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lst.bind(("127.0.0.1", port)); lst.listen(4)
        tr = self.transport
        def acc():
            while True:
                c, a = lst.accept()
                ch = tr.open_forwarded_tcpip_channel(a, ("127.0.0.1", port))
                def pipe(x, y):
                    try:
                        while True:
                            d = x.recv(65536)
                            if not d: break
                            y.sendall(d)
                    except Exception: pass
                    try: y.close()
                    except Exception: pass
                threading.Thread(target=pipe, args=(c, ch), daemon=True).start()
                threading.Thread(target=pipe, args=(ch, c), daemon=True).start()
        threading.Thread(target=acc, daemon=True).start()
        return port

    def cancel_port_forward_request(self, addr, port):
        pass

    def check_channel_x11_request(self, ch, single, proto, cookie, screen):
        ch.x11 = (proto, bytes.fromhex(cookie))
        return True


def xclient(ch, mode):
    """원격 X 클라이언트 흉내: x11 채널로 setup(MIT-MAGIC-COOKIE-1 + 쿠키) → 응답 첫 바이트(1=성공 0=거부)."""
    import struct
    proto, cookie = getattr(ch, "x11", (None, None))
    if not proto:
        return "no x11-req"
    if mode == "bad":
        cookie = bytes(16)
    name = proto.encode() if mode != "none" else b""
    data = cookie if mode != "none" else b""
    pad = lambda b: b + b"\0" * ((4 - len(b) % 4) % 4)
    pkt = b"l\0" + struct.pack("<HHHH", 11, 0, len(name), len(data)) + b"\0\0" + pad(name) + pad(data)
    try:
        x = ch.get_transport().open_x11_channel(("127.0.0.1", 6010))
        x.settimeout(5)
        x.sendall(pkt)
        r = x.recv(1)
        x.close()
        return f"x11 reply {r[0] if r else 'closed'}"
    except Exception as e:
        return f"x11 error {type(e).__name__}"


def execute(ch, cmd):
    time.sleep(0.05)
    if DENY_FILE_ACCESS:
        ch.send_exit_status(255)
        ch.close()
        return
    if "/proc/stat" in cmd:
        ch.sendall((demo_monitor() if DEMO else MON).encode())
    elif cmd.startswith("echo "):
        ch.sendall((cmd[5:] + "\n").encode())
    ch.send_exit_status(0)
    ch.close()


def shell(ch):
    cwd = "/home/test"
    ch.sendall(b"Welcome to Ubuntu 24.04 LTS\r\n$ " if DEMO else b"Welcome to fake sshd\r\n$ ")
    buf = b""
    while True:
        d = ch.recv(4096)
        if not d:
            break
        for b in d:
            c = bytes([b])
            if c == b"\r":
                line = buf.decode("utf-8", "replace")
                buf = b""
                ch.sendall(b"\r\n")
                if line == "exit":
                    ch.send_exit_status(0)
                    ch.close()
                    return
                if line == "pwd":
                    ch.sendall(cwd.encode() + b"\r\n")
                elif line.startswith("cd "):
                    cwd = line[3:]
                elif line.startswith("echo "):
                    ch.sendall(line[5:].encode() + b"\r\n")
                elif line.startswith("xclient "):
                    ch.sendall(xclient(ch, line[8:]).encode() + b"\r\n")
                elif line == "drop":
                    ch.get_transport().close()
                    return
                elif DEMO and line in DEMO_OUTPUT:
                    ch.sendall(DEMO_OUTPUT[line].replace("\n", "\r\n").encode())
                elif line:
                    ch.sendall(f"got: {line}\r\n".encode())
                ch.sendall(b"$ ")
            elif c in (b"\x7f", b"\x08"):
                buf = buf[:-1]
                ch.sendall(b"\b \b")
            else:
                buf += c
                ch.sendall(c)


class Handle(SFTPHandle):
    def stat(self):
        return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno() if hasattr(self, "readfile") else self.writefile.fileno()))


class Stub(SFTPServerInterface):
    def _p(self, path):
        return os.path.join(ROOT, self.canonicalize(path).lstrip("/"))

    def canonicalize(self, path):
        p = posixpath.normpath("/" + path.replace("\\", "/").lstrip("/"))
        return "/" if p in (".", "") else p

    def list_folder(self, path):
        out = []
        for f in os.listdir(self._p(path)):
            a = SFTPAttributes.from_stat(os.lstat(os.path.join(self._p(path), f)))
            a.filename = f
            out.append(a)
        return out

    def stat(self, path):
        try:
            return SFTPAttributes.from_stat(os.stat(self._p(path)))
        except OSError:
            return SFTP_NO_SUCH_FILE

    lstat = stat

    def open(self, path, flags, attr):
        p = self._p(path)
        mode = "rb"
        if flags & os.O_WRONLY or flags & os.O_RDWR:
            mode = "ab" if flags & os.O_APPEND else ("wb" if flags & (os.O_CREAT | os.O_TRUNC) else "r+b")
        try:
            f = open(p, mode)
        except OSError:
            return SFTP_NO_SUCH_FILE
        h = Handle(flags)
        h.filename = p
        h.readfile = f
        h.writefile = f
        return h

    def remove(self, path):
        os.remove(self._p(path))
        return SFTP_OK

    def rename(self, a, b):
        os.rename(self._p(a), self._p(b))
        return SFTP_OK

    def mkdir(self, path, attr):
        os.mkdir(self._p(path))
        return SFTP_OK

    def rmdir(self, path):
        os.rmdir(self._p(path))
        return SFTP_OK

    def chattr(self, path, attr):
        return SFTP_OK


def handle(sock):
    t = paramiko.Transport(sock)
    t.add_server_key(HOSTKEY)
    if not DENY_FILE_ACCESS:
        t.set_subsystem_handler("sftp", SFTPServer, Stub)
    srv = Server(); srv.transport = t
    t.start_server(server=srv)
    while t.is_active():                       # direct-tcpip 채널을 실제 대상에 연결
        ch = t.accept(1)
        if ch is None: continue
        dest = getattr(srv, "dt", {}).pop(ch.get_id(), None)
        if not dest: continue
        try: so = socket.create_connection(dest, 5)
        except OSError: ch.close(); continue
        def pipe(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d: break
                    b.sendall(d)
            except Exception: pass
            for x in (a, b):
                try: x.close()
                except Exception: pass
        threading.Thread(target=pipe, args=(ch, so), daemon=True).start()
        threading.Thread(target=pipe, args=(so, ch), daemon=True).start()


def main():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", PORT))
    s.listen(16)
    print("fake sshd on", PORT, flush=True)
    while True:
        c, _ = s.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
