"""SSH 터널: 로컬 포워딩 / 원격(역방향) 포워딩 / 동적(SOCKS5). 로컬 쪽은 항상 루프백(기본 127.0.0.1, RDP는 세션별 127.x)에만 바인딩.

브라우저 탭을 닫아도 서버가 켜져 있는 동안 유지되고, SSH 연결이 끊기면 5초마다 자동 재연결한다.
"""
import ipaddress
import socket
import struct
import threading
import time
from contextlib import nullcontext

from wst.sshconn import describe, open_chain


def _target(cfg, params):
    def ssh(p):
        return p.get("host"), int(p.get("port") or 22), p.get("username")

    hops = params.get("jumps") or ([params["jump"]] if params.get("jump") else [])
    proxy = params.get("proxy") or {}
    return (cfg.get("type"), cfg.get("destHost"), int(cfg.get("destPort") or 0),
            cfg.get("bindHost") or "127.0.0.1", cfg.get("remoteBind") or "127.0.0.1",
            ssh(params), tuple(ssh(h) for h in hops),
            (proxy.get("type"), proxy.get("host"), int(proxy.get("port") or 0)))


class LocalPortError(RuntimeError):
    pass


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        d = sock.recv(n - len(buf))
        if not d:
            raise ConnectionError("closed")
        buf += d
    return buf


def _pipe(a_recv, b_send, closers):
    try:
        while True:
            d = a_recv(65536)
            if not d:
                break
            b_send(d)
    except Exception:
        pass
    for c in closers:
        try:
            c()
        except Exception:
            pass


class Tunnel:
    """cfg: {type: local|remote|dynamic, listenPort, destHost, destPort, name}
    remote: SSH 서버의 listenPort(remoteBind 주소)로 들어온 연결 → 이 PC에서 destHost:destPort로 연결
    params: sshconn.open_chain 용 접속 정보(비밀값 포함, 재연결 위해 실행 중에만 메모리에 보관)."""

    def __init__(self, tid, cfg, params, on_change, ask):
        self.id, self.cfg, self.params = tid, cfg, params
        self.on_change, self.ask = on_change, ask
        self.state, self.error, self.conns = "starting", None, 0
        self.port = None
        self.client = self.jump = self.listener = None
        self.stopped = False
        self.lock = threading.Lock()
        self.target = _target(cfg, params)          # 비밀값 없이 대상만 보관
        self.started = threading.Event()
        self.start_error = None

    def status(self):
        return {"state": self.state, "error": self.error, "conns": self.conns, "port": self.port}

    def _set(self, state, error=None):
        # 호출자는 self.lock 보유. 중지 뒤의 상태·알림을 되돌리지 않음.
        if self.stopped and state != "off":
            return
        self.state, self.error = state, error
        self.on_change(self.id, self.status())

    # 실행 (블로킹, 스레드에서 호출) ─ 첫 접속 실패는 예외로 돌려줌
    def start(self):
        bind = self.cfg.get("bindHost") or "127.0.0.1"
        try:
            loopback = ipaddress.IPv4Address(bind).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise RuntimeError(f"로컬 터널은 루프백 주소(127.x)에만 열 수 있습니다: {bind}")
        try:
            self._connect()
        except Exception:
            with self.lock:
                if self.stopped:
                    self._close_ssh()
                    raise ValueError("중지된 터널입니다") from None
            raise
        with self.lock:
            if self.stopped:
                self._close_ssh()
                raise ValueError("중지된 터널입니다")
        if self.cfg.get("type") == "remote":
            try:
                self._request_remote()
            except Exception:
                self._close_ssh()
                raise
            with self.lock:                                # 중지 확인과 "켜짐" 표시를 한 번에 (사이에 중지되면 다시 켜지지 않게)
                if self.stopped:
                    self._close_ssh()
                    raise ValueError("중지된 터널입니다")
                self._set("on")
            threading.Thread(target=self._watch, daemon=True).start()
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):       # Windows: 다른 프로세스가 같은 포트를 가로채지 못하게
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind((bind, int(self.cfg.get("listenPort") or 0)))
        except OSError as e:
            listener.close()
            self._close_ssh()
            raise LocalPortError(f"로컬 포트 {bind}:{self.cfg.get('listenPort')}를 열 수 없습니다 (이미 사용 중?): {e.strerror}")
        listener.listen(32)
        with self.lock:
            if self.stopped:                              # 접속·바인드 중에 중지를 누름
                listener.close()
                self._close_ssh()
                raise ValueError("중지된 터널입니다")
            self.listener = listener
            self.port = listener.getsockname()[1]
            self._set("on")
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _connect(self):
        p = dict(self.params)
        if p.get("jump"):
            p["jump"] = dict(p["jump"])
        self.client, self.jump = open_chain(p, self.ask)

    def _request_remote(self):
        port = int(self.cfg.get("listenPort") or 0)
        try:
            self.port = self.client.get_transport().request_port_forward(self.cfg.get("remoteBind") or "127.0.0.1", port, self._remote_conn)
        except Exception as e:
            raise RuntimeError(f"서버 쪽 포트 {port}를 열 수 없습니다 (이미 사용 중이거나 AllowTcpForwarding/GatewayPorts 설정 확인): {e}")

    def _remote_conn(self, chan, origin, server):
        def run():
            try:
                sock = socket.create_connection((self.cfg.get("destHost") or "127.0.0.1", int(self.cfg["destPort"])), 10)
                sock.settimeout(None)
            except Exception:
                chan.close()
                return
            with self.lock:
                if self.stopped:
                    sock.close()
                    chan.close()
                    return
                self.conns += 1
                self.on_change(self.id, self.status())
            closers = (sock.close, chan.close)
            t = threading.Thread(target=_pipe, args=(chan.recv, sock.sendall, closers), daemon=True)
            t.start()
            _pipe(sock.recv, chan.sendall, closers)
            t.join()
            with self.lock:
                if self.stopped:
                    return
                self.conns = max(0, self.conns - 1)
                self.on_change(self.id, self.status())
        threading.Thread(target=run, daemon=True).start()

    def _close_ssh(self):
        for c in (self.client, self.jump):
            if c:
                try:
                    c.close()
                except Exception:
                    pass
        self.client = self.jump = None

    def _watch(self):
        """SSH 연결이 끊기면 자동 재연결."""
        while not self.stopped:
            time.sleep(2)
            t = self.client.get_transport() if self.client else None
            if t and t.is_active():
                continue
            with self.lock:
                if self.stopped:
                    return
                self._set("reconnecting", "SSH 연결 끊김 — 재연결 중")
            self._close_ssh()
            while not self.stopped:
                try:
                    self._connect()
                except Exception as e:
                    with self.lock:
                        if self.stopped:             # 접속 시도 중에 ■중지됨
                            return
                        self._set("reconnecting", describe(e)[0] + " — 5초 후 재시도")
                    time.sleep(5)
                    continue
                if self.cfg.get("type") == "remote" and not self.stopped:
                    try:
                        self._request_remote()
                    except Exception as e:
                        self._close_ssh()
                        with self.lock:
                            if self.stopped:
                                return
                            self._set("reconnecting", str(e)[:120] + " — 5초 후 재시도")
                        time.sleep(5)
                        continue
                with self.lock:
                    if self.stopped:                 # 중지된 뒤에 접속이 성공함 → 새 연결 정리
                        self._close_ssh()
                        return
                    self._set("on")
                break

    def _accept_loop(self):
        while not self.stopped:
            try:
                sock, peer = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(sock, peer), daemon=True).start()

    def _open(self, host, port, peer):
        t = self.client.get_transport() if self.client else None
        if not t or not t.is_active():
            raise ConnectionError("SSH 연결 없음")
        return t.open_channel("direct-tcpip", (host, int(port)), peer, timeout=10)

    def _handle(self, sock, peer):
        chan = None
        try:
            if self.cfg.get("type") == "dynamic":
                host, port = self._socks5(sock)
                try:
                    chan = self._open(host, port, peer)
                except Exception:
                    sock.sendall(b"\x05\x05\x00\x01" + bytes(6))      # connection refused
                    raise
                sock.sendall(b"\x05\x00\x00\x01" + bytes(6))
            else:
                chan = self._open(self.cfg["destHost"], self.cfg["destPort"], peer)
        except Exception:
            sock.close()
            if chan:
                chan.close()
            return
        with self.lock:
            if self.stopped:
                sock.close()
                chan.close()
                return
            self.conns += 1
            self.on_change(self.id, self.status())
        closers = (sock.close, chan.close)
        t = threading.Thread(target=_pipe, args=(chan.recv, sock.sendall, closers), daemon=True)
        t.start()
        _pipe(sock.recv, chan.sendall, closers)
        t.join()
        with self.lock:
            if self.stopped:
                return
            self.conns = max(0, self.conns - 1)
            self.on_change(self.id, self.status())

    @staticmethod
    def _socks5(sock):
        ver, n = _recv_exact(sock, 2)
        if ver != 5:
            raise ConnectionError("not socks5")
        _recv_exact(sock, n)
        sock.sendall(b"\x05\x00")                     # 인증 없음 (127.0.0.1 전용)
        ver, cmd, _, atyp = _recv_exact(sock, 4)
        if atyp == 1:
            host = str(ipaddress.IPv4Address(_recv_exact(sock, 4)))
        elif atyp == 3:
            host = _recv_exact(sock, _recv_exact(sock, 1)[0]).decode("idna")
        elif atyp == 4:
            host = str(ipaddress.IPv6Address(_recv_exact(sock, 16)))
        else:
            raise ConnectionError("bad atyp")
        port = struct.unpack(">H", _recv_exact(sock, 2))[0]
        if cmd != 1:                                  # CONNECT만 지원
            sock.sendall(b"\x05\x07\x00\x01" + bytes(6))
            raise ConnectionError("unsupported cmd")
        return host, port

    def stop(self):
        with self.lock:
            self.stopped = True
            listener = self.listener
            self.conns = 0
            self._set("off")
        if listener:
            try:
                listener.close()
            except Exception:
                pass
        self._close_ssh()
        self.params = None


class TunnelManager:
    def __init__(self):
        self.tunnels = {}
        self.listeners = []          # 상태 변경 콜백 (tid, status)
        self.lock = threading.Lock()

    def _notify(self, tid, st):
        for cb in list(self.listeners):
            cb(tid, st)

    def status(self):
        return {tid: t.status() for tid, t in self.tunnels.items()}

    def start(self, tid, cfg, params, ask, guard=None):
        """블로킹. 성공 시 Tunnel 반환, 실패 시 예외."""
        deadline = time.monotonic() + 130
        target = _target(cfg, params)
        while True:
            with guard() if guard else nullcontext():    # RDP 세대 확인과 대상 교체를 한 번에
                with self.lock:
                    old = self.tunnels.get(tid)
                    if not old or old.started.is_set():
                        if old and old.state in ("on", "reconnecting"):
                            if old.target == target and (not cfg.get("listenPort") or int(cfg["listenPort"]) == old.port):
                                return old
                            old.stop()
                        t = Tunnel(tid, cfg, params, self._notify, ask)
                        self.tunnels[tid] = t
                        break
            # 시작 완료는 어떤 락도 쥐지 않고 기다림
            if not old.started.wait(max(0, deadline - time.monotonic())):
                raise ValueError("터널 연결 대기 시간이 초과되었습니다")
            if old.target == target and old.start_error is not None:
                raise old.start_error
        try:
            with t.lock:
                if t.stopped:
                    raise ValueError("중지된 터널입니다")
                t._set("starting")
            t.start()
            with t.lock:
                if t.stopped:
                    raise ValueError("중지된 터널입니다")
        except Exception as e:
            with t.lock:
                t.params = None
                if t.stopped:
                    e = ValueError("중지된 터널입니다")
                t.start_error = e
                t._set("error", describe(e)[0] if not isinstance(e, RuntimeError) else str(e))
            raise e
        finally:
            t.started.set()
        return t

    def stop(self, tid):
        t = self.tunnels.get(tid)
        if t:
            t.stop()

    def stop_all(self):
        for t in list(self.tunnels.values()):
            t.stop()


manager = TunnelManager()
