"""도구 메뉴: 포트 스캐너, 이 PC의 열린 포트, TFTP 서버, HTTP 파일 서버, SSH 키 생성.

모두 "이 PC에서" 동작하므로 LOCAL_MODE(127.0.0.1 바인딩)일 때만 api.py가 호출한다.
"""
import asyncio
import http.server
import ipaddress
import os
import socket
import struct
import subprocess
import threading
import time
from functools import partial
from pathlib import Path

import re

from wst import common


# ── 포트 스캐너 ────────────────────────────────────────────
def parse_ports(spec):
    out = set()
    for part in (spec or "").replace(" ", "").split(","):
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        if not (1 <= lo <= hi <= 65535):
            raise ValueError(f"포트 범위가 잘못됐습니다: {part}")
        out.update(range(lo, hi + 1))
    if len(out) > 20000:
        raise ValueError("한 번에 20,000개 포트까지만 검사합니다")
    return sorted(out)


def parse_hosts(spec):
    spec = (spec or "").strip()
    if "/" in spec:
        net = ipaddress.ip_network(spec, strict=False)
        if net.num_addresses > 1024:
            raise ValueError("한 번에 /22(1024개 주소)까지만 검사합니다")
        return [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]
    m = re.fullmatch(r"(\d+\.\d+\.\d+)\.(\d+)-(\d+)", spec)   # 192.168.0.10-20 (호스트 이름의 '-'는 범위가 아님)
    if m:
        a, b = int(m[2]), int(m[3])
        if not 0 <= a <= b <= 255:
            raise ValueError("범위는 0~255 안에서 작은 수-큰 수로 적으세요")
        return [f"{m[1]}.{i}" for i in range(a, b + 1)]
    return [spec]


COMMON = {21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns", 69: "tftp", 80: "http", 110: "pop3", 135: "msrpc",
          139: "netbios", 143: "imap", 161: "snmp", 389: "ldap", 443: "https", 445: "smb", 465: "smtps", 514: "syslog",
          587: "submission", 636: "ldaps", 873: "rsync", 993: "imaps", 995: "pop3s", 1433: "mssql", 1521: "oracle",
          2049: "nfs", 2375: "docker", 3000: "dev-http", 3306: "mysql", 3389: "rdp", 5432: "postgres", 5900: "vnc",
          5985: "winrm", 6379: "redis", 8000: "http-alt", 8080: "http-proxy", 8443: "https-alt", 9200: "elasticsearch",
          11211: "memcached", 27017: "mongodb"}


async def scan(hosts, ports, timeout=0.8, progress=None):
    """열린 포트 [{host, port, service, banner}]. progress(done, total) 콜백."""
    found, total, done = [], len(hosts) * len(ports), 0
    if total > 200_000:
        raise ValueError(f"한 번에 20만 개(호스트×포트)까지만 검사합니다 (지금 {total:,}개)")

    async def one(h, p):
        nonlocal done
        if True:
            try:
                r, w = await asyncio.wait_for(asyncio.open_connection(h, p), timeout)
                banner = ""
                try:
                    banner = (await asyncio.wait_for(r.read(120), 0.6)).decode("utf-8", "replace").strip()
                except Exception:
                    pass
                w.close()
                found.append({"host": h, "port": p, "service": COMMON.get(p, ""), "banner": banner[:120]})
            except Exception:
                pass
            done += 1
            if progress and done % 200 == 0:
                await progress(done, total)
    jobs = ((h, p) for h in hosts for p in ports)          # 작업자 256개가 차례로 꺼내 씀 (코루틴을 한꺼번에 만들지 않음)

    async def worker():
        for h, p in jobs:
            await one(h, p)
    await asyncio.gather(*(worker() for _ in range(min(256, total or 1))))
    return sorted(found, key=lambda x: (tuple(int(c) if c.isdigit() else 0 for c in x["host"].split(".")), x["port"]))


# ── 이 PC에서 열려 있는(LISTEN) 포트 ────────────────────────
def listening():
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, creationflags=common.NO_WINDOW,
                         encoding="cp949", errors="replace").stdout
    out6 = subprocess.run(["netstat", "-ano", "-p", "TCPv6"], capture_output=True, text=True, creationflags=common.NO_WINDOW,
                          encoding="cp949", errors="replace").stdout
    names = {}
    tl = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, creationflags=common.NO_WINDOW,
                        encoding="cp949", errors="replace").stdout
    for line in tl.splitlines():
        f = [x.strip('"') for x in line.split('","')]
        if len(f) >= 2 and f[1].isdigit():
            names[f[1]] = f[0]
    res, seen = [], set()
    for line in (out + out6).splitlines():
        f = line.split()
        if len(f) >= 5 and f[0] == "TCP" and f[3] == "LISTENING":
            addr, port = f[1].rsplit(":", 1)
            key = (addr, port, f[4])
            if key in seen:
                continue
            seen.add(key)
            res.append({"addr": addr, "port": int(port), "pid": int(f[4]), "proc": names.get(f[4], "")})
    return sorted(res, key=lambda x: (x["port"], x["addr"]))


# ── TFTP 서버 (RFC 1350, octet/netascii, 블록 512) ─────────────
class TftpServer:
    def __init__(self, root, bind="0.0.0.0", port=69, allow_write=False, on_log=None):
        self.root, self.bind, self.port, self.allow_write = Path(root).resolve(), bind, int(port), allow_write
        self.on_log = on_log or (lambda m: None)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind, self.port))
        self.stopped = False
        self.log = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _say(self, msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        self.log = (self.log + [line])[-200:]
        self.on_log(line)

    def _path(self, name):
        p = (self.root / name.lstrip("/\\")).resolve()
        if self.root not in p.parents and p != self.root:
            raise PermissionError("폴더 밖 경로")
        return p

    def _loop(self):
        while not self.stopped:
            try:
                data, peer = self.sock.recvfrom(1500)
            except OSError:
                return
            try:
                if len(data) < 4:
                    continue
                op = struct.unpack(">H", data[:2])[0]
                parts = data[2:].split(b"\0")
                if op in (1, 2) and len(parts) >= 2:
                    threading.Thread(target=self._xfer, args=(op, parts[0].decode("utf-8", "replace"),
                                                              parts[1].decode("ascii", "replace").lower(), peer),
                                     daemon=True).start()
            except Exception as e:                        # 패킷 하나가 이상해도 서버는 계속
                self._say(f"잘못된 요청 무시 ({peer[0]}): {e}")

    @staticmethod
    def _err(s, peer, code, msg):
        s.sendto(struct.pack(">HH", 5, code) + msg.encode() + b"\0", peer)

    def _xfer(self, op, name, mode, peer):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((self.bind, 0))
        s.settimeout(3)
        try:
            path = self._path(name)
            if op == 1:                                   # 읽기 (장비가 받아 감)
                data = path.read_bytes()
                if mode == "netascii":
                    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                blk = 1
                for i in range(0, len(data) + 1, 512):
                    chunk = data[i:i + 512]
                    for _ in range(5):
                        s.sendto(struct.pack(">HH", 3, blk & 0xFFFF) + chunk, peer)
                        try:
                            ack, _ = s.recvfrom(516)
                            if struct.unpack(">HH", ack[:4]) == (4, blk & 0xFFFF):
                                break
                        except socket.timeout:
                            continue
                    else:
                        raise TimeoutError("응답 없음")
                    blk += 1
                    if len(chunk) < 512:
                        break
                self._say(f"보냄 {name} → {peer[0]} ({len(data):,}B)")
            else:                                         # 쓰기 (장비가 백업을 올림)
                if not self.allow_write:
                    self._err(s, peer, 2, "write disabled")
                    self._say(f"거부(쓰기 꺼짐) {name} ← {peer[0]}")
                    return
                path.parent.mkdir(parents=True, exist_ok=True)
                buf, blk = bytearray(), 0
                s.sendto(struct.pack(">HH", 4, 0), peer)
                while True:
                    d, src = s.recvfrom(516)
                    if src != peer or len(d) < 4:                 # 다른 곳에서 온 패킷·잘린 패킷은 무시
                        continue
                    op2, b = struct.unpack(">HH", d[:4])
                    if op2 != 3:                                   # ERROR 등 → 받은 것은 버리고 기존 파일 유지
                        raise ConnectionError(f"업로드 중단 (op {op2})")
                    s.sendto(struct.pack(">HH", 4, b), peer)
                    if b != (blk + 1) & 0xFFFF:                    # 재전송된 이전 블록
                        continue
                    buf += d[4:]
                    blk += 1
                    if len(d) - 4 < 512:
                        break
                tmp = path.with_suffix(path.suffix + ".part")
                tmp.write_bytes(bytes(buf))
                os.replace(tmp, path)
                self._say(f"받음 {name} ← {peer[0]} ({len(buf):,}B)")
        except FileNotFoundError:
            self._err(s, peer, 1, "file not found")
            self._say(f"없는 파일 {name} ({peer[0]})")
        except Exception as e:
            self._err(s, peer, 0, str(e)[:60])
            self._say(f"오류 {name} ({peer[0]}): {e}")
        finally:
            s.close()

    def stop(self):
        self.stopped = True
        self.sock.close()


# ── HTTP 파일 서버 (폴더 공유, 목록 보기) ─────────────────────
class HttpServer:
    def __init__(self, root, bind="0.0.0.0", port=8000):
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):              # 콘솔·server.log에 요청마다 찍지 않음
                pass
        handler = partial(Quiet, directory=str(Path(root).resolve()))
        self.httpd = http.server.ThreadingHTTPServer((bind, int(port)), handler)
        self.bind, self.port, self.root = bind, int(port), str(root)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


SERVERS = {}            # "tftp" / "http" → 실행 중인 서버


def local_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ips)


def servers_status():
    out = {}
    for k, s in SERVERS.items():
        out[k] = {"bind": s.bind, "port": s.port, "root": str(s.root), "log": getattr(s, "log", [])[-30:],
                  "write": getattr(s, "allow_write", None)}
    return out


def start_server(kind, root, bind, port, write=False):
    if kind in SERVERS:
        raise RuntimeError("이미 실행 중입니다")
    if not Path(root).is_dir():
        raise ValueError(f"폴더가 없습니다: {root}")
    try:
        SERVERS[kind] = TftpServer(root, bind, port or 69, write) if kind == "tftp" else HttpServer(root, bind, port or 8000)
    except OSError as e:
        raise RuntimeError(f"포트 {port}를 열 수 없습니다 (이미 사용 중이거나 방화벽): {e.strerror or e}")


def stop_server(kind):
    s = SERVERS.pop(kind, None)
    if s:
        s.stop()


# ── SSH 키 생성 ────────────────────────────────────────────
def keygen(kind="ed25519", bits=4096, comment="", passphrase="", save_as=""):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
    if kind == "rsa":
        k = rsa.generate_private_key(public_exponent=65537, key_size=int(bits))
    elif kind == "ecdsa":
        k = ec.generate_private_key(ec.SECP256R1())
    else:
        k = ed25519.Ed25519PrivateKey.generate()
    enc = serialization.BestAvailableEncryption(passphrase.encode()) if passphrase else serialization.NoEncryption()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, enc).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    pub = f"{pub} {comment}".strip()
    saved = None
    if save_as:
        p = Path(os.path.expandvars(os.path.expanduser(save_as)))
        if p.exists() or p.with_suffix(p.suffix + ".pub").exists():
            raise FileExistsError(f"이미 있는 파일입니다: {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(priv, encoding="utf-8")
        Path(str(p) + ".pub").write_text(pub + "\n", encoding="utf-8")
        try:                                         # 개인키는 현재 사용자만 읽게 (OpenSSH가 권한을 검사)
            subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME')}:F"],
                           capture_output=True, creationflags=common.NO_WINDOW)
        except Exception:
            pass
        saved = str(p)
    return {"public": pub, "saved": saved, "private": None if saved else priv}
