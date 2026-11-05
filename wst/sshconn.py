"""SSH 접속: 키 로드, 호스트 키 TOFU, 점프 호스트 체인, 오류 설명."""
import base64
import hashlib
import io
import os
import ipaddress
import re
import shlex
import socket
import threading
from pathlib import Path

import paramiko

from wst import vault
from wst import common
from wst.common import KNOWN_HOSTS

_known_lock = threading.Lock()


class NeedPassphrase(Exception):
    """개인키 암호가 필요함 → 브라우저에서 물어보고 재시도."""


def _load_pkey(text, passphrase):
    if text.lstrip().startswith("PuTTY-User-Key-File"):         # .ppk → OpenSSH로 바꿔서 읽음
        from wst import ppk
        try:
            text, passphrase = ppk.ppk_to_openssh(text, passphrase), None
        except ppk.NeedPassphrase as e:
            raise NeedPassphrase(*e.args)
    text = text.strip() + "\n"
    wrong = False
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text), password=passphrase or None)
        except paramiko.PasswordRequiredException:
            raise NeedPassphrase()
        except paramiko.SSHException as e:
            # 틀린 암호: OpenSSH 형식은 "checkints do not match", PEM은 "Bad password ..." (paramiko 5.0 실측)
            msg = str(e).lower()
            wrong = wrong or any(w in msg for w in ("decrypt", "checkints", "bad password"))
        except Exception:
            pass
    if passphrase and wrong:
        raise NeedPassphrase("키 암호가 틀렸습니다")
    raise ValueError("개인키를 읽을 수 없습니다 (지원: Ed25519/ECDSA/RSA, OpenSSH·PEM 형식)")


def pkey_from(p):
    if p.get("auth") == "keyfile" or (p.get("keyPath") and not p.get("key")):
        if not common.LOCAL_MODE:
            raise PermissionError("원격 모드에서는 이 PC의 개인키 파일을 쓸 수 없습니다")
        if not p.get("keyPath"):
            raise ValueError("개인키 파일 경로가 비어 있습니다")
        path = Path(os.path.expandvars(os.path.expanduser(p["keyPath"])))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise ValueError(f"개인키 파일을 열 수 없습니다: {path} ({e.strerror})")
        return _load_pkey(text, p.get("passphrase"))
    if p.get("key"):
        return _load_pkey(p["key"], p.get("passphrase"))
    return None


def fingerprint(key):
    """OpenSSH 스타일 지문 (SHA256:base64)."""
    raw = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(raw).decode().rstrip("=")


class AskUserPolicy(paramiko.MissingHostKeyPolicy):
    """처음 보는 호스트 키 → 브라우저에 지문을 보여주고 승인받음."""

    def __init__(self, ask):
        self.ask = ask  # (host, keytype, fingerprint) -> bool  (스레드에서 호출)

    def missing_host_key(self, client, hostname, key):
        if not self.ask(hostname, key.get_name(), fingerprint(key)):
            raise paramiko.SSHException("사용자가 호스트 키를 거부했습니다")
        client.get_host_keys().add(hostname, key.get_name(), key)
        with _known_lock:                     # 파일을 다시 읽어서 추가 (동시에 접속한 다른 연결이 저장한 키를 덮어쓰지 않게)
            hk = paramiko.HostKeys()
            if KNOWN_HOSTS.exists():
                hk.load(str(KNOWN_HOSTS))
            hk.add(hostname, key.get_name(), key)
            hk.save(str(KNOWN_HOSTS))


def _hk_name(host, port):
    return host if int(port or 22) == 22 else f"[{host}]:{int(port)}"


def known_hosts():
    """저장된 호스트 키 목록 [{name, type, fingerprint}]"""
    with _known_lock:
        hk = paramiko.HostKeys()
        if KNOWN_HOSTS.exists():
            hk.load(str(KNOWN_HOSTS))
    return [{"name": n, "type": t, "fingerprint": fingerprint(k)} for n in hk.keys() for t, k in hk[n].items()]


def forget_host_key(host=None, port=22, name=None):
    """호스트 키 삭제 → 다음 접속 때 다시 확인 창이 뜸. 지운 항목 수 반환."""
    name = name or _hk_name(host, port)
    with _known_lock:
        hk = paramiko.HostKeys()
        if KNOWN_HOSTS.exists():
            hk.load(str(KNOWN_HOSTS))
        if name not in hk:
            return 0
        del hk[name]
        hk.save(str(KNOWN_HOSTS))
        return 1


class HopError(Exception):
    """어느 단계(점프 호스트/대상)에서 실패했는지 표시."""

    def __init__(self, stage, err, which="target"):
        super().__init__(stage)
        self.stage, self.err, self.which = stage, err, which


def connect_one(p, ask, sock=None):
    client = paramiko.SSHClient()
    with _known_lock:
        if KNOWN_HOSTS.exists():
            client.load_host_keys(str(KNOWN_HOSTS))
    client.set_missing_host_key_policy(AskUserPolicy(ask))
    typed = p.get("password"), p.get("passphrase")          # 사용자가 이번에 입력한 값 (저장소 값과 구분)
    vault.fill(p)                                            # 비어 있으면 저장된 비밀번호·키 암호 사용
    pkey = pkey_from(p)
    try:
        if sock is None:
            target = common.check_remote_target(p["host"])
            if not common.LOCAL_MODE:
                # 키 확인 이름은 원래 host로 유지하고, TCP 연결만 검사된 IP로 연다.
                sock = socket.create_connection((target, int(p.get("port") or 22)), 10)
        client.connect(
            hostname=p["host"], port=int(p.get("port") or 22), username=p["username"],
            password=p.get("password") or None, pkey=pkey, sock=sock,
            timeout=10, banner_timeout=15, auth_timeout=20,
            look_for_keys=False, allow_agent=bool(p.get("agent")) and common.LOCAL_MODE,   # Pageant / Windows OpenSSH 에이전트
            compress=bool(p.get("compress")),
        )
    except Exception:
        client.close()
        if sock is not None:
            sock.close()
        raise
    client.get_transport().set_keepalive(int(p.get("keepalive") or 30))
    if p.get("save") and vault.VAULT and common.LOCAL_MODE and (typed[0] or typed[1]):   # 접속에 성공한 값만 저장
        try:
            vault.VAULT.set(vault.key_of(p), **{k: v for k, v in (("password", typed[0]), ("passphrase", typed[1])) if v})
        except vault.Locked:
            pass
    return client


def proxy_socket(proxy, host, port):
    """SOCKS5(인증 없음 / 사용자:비밀번호) 또는 HTTP CONNECT 프록시를 거친 소켓. proxy: {type, host, port, user, password}"""
    import socket
    import struct
    def endpoint(h, p):
        if not isinstance(h, str) or not h or re.search(r'[\x00-\x20\x7f\s]', h):
            raise ValueError("프록시 주소에 공백·제어문자를 쓸 수 없습니다")
        if isinstance(p, bool) or not isinstance(p, (int, str)) or not re.fullmatch(r'[0-9]+', str(p)) or not 1 <= int(p) <= 65535:
            raise ValueError("포트는 1~65535 정수여야 합니다")
        if '[' in h or ']' in h:
            if not (h.startswith('[') and h.endswith(']')):
                raise ValueError("대괄호는 IPv6 리터럴에만 사용할 수 있습니다")
            try:
                ipaddress.IPv6Address(h[1:-1])
            except ValueError:
                raise ValueError("대괄호는 IPv6 리터럴에만 사용할 수 있습니다") from None
            h = h[1:-1]
        return h, int(p)

    host, port = endpoint(host, port)
    proxy_host, proxy_port = endpoint(proxy.get("host"), proxy.get("port"))
    connect_host = host
    try:
        if ipaddress.ip_address(host).version == 6:
            connect_host = f"[{host}]"
    except ValueError:
        pass
    if not common.LOCAL_MODE:
        try:                     # 프록시 너머 대상도 이 PC 자신이면 거부 (프록시로 우회 방지)
            common.check_remote_target(host)
        except PermissionError:
            raise
        except OSError:          # 이 PC에서 안 풀리는 이름은 프록시가 해석 — 대상 이름 그대로 전달
            pass
    target = common.check_remote_target(proxy_host)
    sock = socket.create_connection((target, proxy_port), 10)
    try:
        if proxy.get("type") == "http":
            auth = ""
            if proxy.get("user"):
                cred = base64.b64encode(f'{proxy["user"]}:{proxy.get("password") or ""}'.encode()).decode()
                auth = f"Proxy-Authorization: Basic {cred}\r\n"
            sock.sendall(f"CONNECT {connect_host}:{port} HTTP/1.1\r\nHost: {connect_host}:{port}\r\n{auth}\r\n".encode())
            resp = b""
            while b"\r\n\r\n" not in resp and len(resp) < 8192:   # 한 바이트씩: 뒤따르는 SSH 배너를 먹지 않게
                d = sock.recv(1)
                if not d:
                    break
                resp += d
            line = resp.split(b"\r\n", 1)[0].decode(errors="replace")
            if " 200" not in line:
                raise ConnectionError(f"HTTP 프록시 거부: {line}")
            return sock
        methods = b"\x00\x02" if proxy.get("user") else b"\x00"
        sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
        def rx(n):
            b = b""
            while len(b) < n:
                d = sock.recv(n - len(b))
                if not d:
                    raise ConnectionError("SOCKS5 프록시가 연결을 끊었습니다")
                b += d
            return b
        _, m = rx(2)
        if m == 2:
            u, pw = proxy["user"].encode(), (proxy.get("password") or "").encode()
            sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(pw)]) + pw)
            if rx(2)[1:2] != b"\x00":
                raise ConnectionError("SOCKS5 프록시 인증 실패")
        elif m != 0:
            raise ConnectionError("SOCKS5 프록시가 인증 방식을 거부했습니다")
        hb = host.encode("idna")
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + struct.pack(">H", int(port)))
        r = rx(4)
        if r[1] != 0:
            raise ConnectionError(f"SOCKS5 프록시가 {host}:{port} 연결을 거부했습니다 (코드 {r[1] if len(r) > 1 else '?'})")
        rest = {1: 4, 4: 16}.get(r[3])                # 응답의 바인드 주소 + 포트(2) 읽어 버림
        rx((rest or rx(1)[0]) + 2)
        return sock
    except Exception:
        sock.close()
        raise


class _Hops:
    """경유 SSH 연결들 (닫을 때 뒤에서부터)."""

    def __init__(self, clients):
        self.clients = clients

    def close(self):
        for c in reversed(self.clients):
            try:
                c.close()
            except Exception:
                pass


def hop_names(n):
    """점프 호스트 이름: 1개면 'jump'(예전과 같음), 여러 개면 jump0, jump1…"""
    return ["jump"] if n == 1 else [f"jump{i}" for i in range(n)]


def open_chain(p, ask):
    """(프록시 →) (점프 호스트 …) → 대상까지 SSH 연결. 반환: (client, 경유 연결 묶음|None)
    p["jumps"] = [홉…] 이 있으면 여러 단계, 없으면 p["jump"] 하나. p["proxy"] = 첫 연결에 쓸 프록시."""
    hops = list(p.get("jumps") or ([p["jump"]] if p.get("jump") else []))
    names = hop_names(len(hops))
    proxy = p.get("proxy") if (p.get("proxy") or {}).get("host") else None
    clients, sock = [], None
    try:
        for i, (h, name) in enumerate(zip(hops, names)):
            if i == 0 and proxy:
                try:
                    sock = proxy_socket(proxy, h["host"], h.get("port") or 22)
                except Exception as e:
                    raise HopError(f"프록시({proxy['host']})", e, name)
            try:
                c = connect_one(h, ask, sock)
            except Exception as e:
                raise HopError(f"점프 호스트({h['host']})", e, name)
            clients.append(c)
            nxt = hops[i + 1] if i + 1 < len(hops) else p
            try:
                sock = c.get_transport().open_channel("direct-tcpip", (nxt["host"], int(nxt.get("port") or 22)),
                                                      ("127.0.0.1", 0), timeout=10)
            except Exception as e:
                raise HopError(f"점프 호스트 → {nxt['host']} 연결", e, name)
        if not hops and proxy:
            try:
                sock = proxy_socket(proxy, p["host"], p.get("port") or 22)
            except Exception as e:
                raise HopError(f"프록시({proxy['host']})", e, "target")
        try:
            client = connect_one(p, ask, sock)
        except Exception as e:
            raise HopError(f"대상 서버({p['host']})" if hops else "", e, "target")
    except Exception:
        _Hops(clients).close()
        raise
    return client, (_Hops(clients) if clients else None)


def describe(e):
    """예외 → (사용자용 메시지, 코드). 코드: passphrase:<which> | auth:<which> | hostkey | None"""
    err = e.err if isinstance(e, HopError) else e
    which = e.which if isinstance(e, HopError) else "target"
    stage = f"[{e.stage}] " if isinstance(e, HopError) and e.stage else ""
    if isinstance(err, NeedPassphrase):
        return f"{stage}{(err.args[0] if err.args else '') or '개인키에 암호가 걸려 있습니다'}.", f"passphrase:{which}"
    if isinstance(err, paramiko.BadHostKeyException):
        return (f"{stage}⚠ 호스트 키가 저장된 값과 다릅니다! (MITM 가능성)\n"
                f"저장됨: {err.expected_key.get_name()} {fingerprint(err.expected_key)}\n"
                f"수신됨: {err.key.get_name()} {fingerprint(err.key)}\n"
                f"서버를 재설치·교체한 게 확실하면 [새 키로 교체]를 누르세요."), f"hostkey:{which}"
    if isinstance(err, paramiko.AuthenticationException):
        return f"{stage}인증 실패 — 사용자명/비밀번호/키를 확인하세요.", f"auth:{which}"
    if isinstance(err, paramiko.ChannelException):
        return f"{stage}실패 — 점프 호스트가 대상에 연결하지 못했습니다 (주소/포트/AllowTcpForwarding 확인)", None
    return f"{stage}접속 실패: {err}", None


def scrub(p):
    """비밀값을 메모리에서 지움."""
    for d in (p, p.get("jump") or {}, *(p.get("jumps") or []), p.get("proxy") or {}):
        for k in ("password", "key", "passphrase"):
            d.pop(k, None)


def exec_sh(client, script, timeout=10):
    """같은 SSH 연결에서 sh 스크립트 실행 → (stdout 바이트, 종료코드).
    로그인 셸이 csh/fish여도 되도록 항상 sh -c 로 감싼다."""
    stdin, stdout, stderr = client.exec_command("sh -c " + shlex.quote(script), timeout=timeout)
    out = stdout.read()
    return out, stdout.channel.recv_exit_status()


def exec_text(client, script, timeout=10):
    """exec_sh의 문자열 버전 (모니터링·폴더 추적용)."""
    out, code = exec_sh(client, script, timeout)
    return out.decode("utf-8", "replace"), code
