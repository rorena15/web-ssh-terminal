"""VNC: 브라우저 noVNC ↔ WebSocket(/vnc) ↔ 이 서버 ↔ TCP(또는 SSH 게이트웨이 채널) ↔ VNC 서버.

noVNC는 WebSocket을 열자마자 RFB 바이트를 주고받으므로 대상 정보를 첫 메시지로 받을 수 없다.
→ /api의 vncOpen이 먼저 대상에 연결해 두고 일회용 표(ticket)를 주면, /vnc?vt=<표>가 그 연결을 이어받는다.
VNC 비밀번호 인증은 noVNC(브라우저)가 처리한다(RFB 프로토콜 특성상).
"""
import asyncio
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

from websockets.exceptions import ConnectionClosed

from wst import common

PENDING = {}            # 표 → (소켓 같은 것, 닫을 것들, 만료 시각)


def open_target(host, port, gateway=None, ask=None):
    """블로킹. 대상에 연결하고 표를 돌려줌."""
    closers = []
    if gateway:
        from wst.sshconn import open_chain
        client, jump = open_chain(gateway, ask)
        closers += [c for c in (client, jump) if c]
        try:
            sock = client.get_transport().open_channel("direct-tcpip", (host, int(port)), ("127.0.0.1", 0), timeout=10)
        except Exception:
            for c in closers:
                c.close()
            raise
    else:
        target = common.check_remote_target(host)
        sock = socket.create_connection((target, int(port)), 10)
        sock.settimeout(None)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    now = time.time()
    for k in [k for k, v in list(PENDING.items()) if v[2] < now]:
        old = PENDING.pop(k, None)                      # 타이머가 먼저 지웠을 수 있음
        if old:
            _close(old)
    tok = secrets.token_urlsafe(18)
    PENDING[tok] = (sock, closers, now + 60)
    t = threading.Timer(61, lambda: PENDING.pop(tok, None) and _close((sock, closers, 0)))   # 안 쓰인 표 정리
    t.daemon = True
    t.start()
    return tok


def _close(item):
    sock, closers, _ = item
    for c in (sock, *closers):
        try:
            c.close()
        except Exception:
            pass


async def vnc_handler(ws):
    tok = parse_qs(urlsplit(ws.request.path).query).get("vt", [""])[0]
    item = PENDING.pop(tok, None)
    if item and item[2] < time.time():
        _close(item)
        item = None
    if not item:
        await ws.close(1008, "expired")
        return
    sock = item[0]
    loop = asyncio.get_running_loop()
    done = threading.Event()

    def pump():
        try:
            while True:
                d = sock.recv(65536)
                if not d:
                    break
                asyncio.run_coroutine_threadsafe(ws.send(d), loop).result()
        except Exception:
            pass
        done.set()
        asyncio.run_coroutine_threadsafe(ws.close(), loop)

    threading.Thread(target=pump, daemon=True).start()
    try:
        async for msg in ws:
            if isinstance(msg, bytes):
                await asyncio.to_thread(sock.sendall, msg)
    except (ConnectionClosed, OSError):
        pass
    finally:
        _close(item)
