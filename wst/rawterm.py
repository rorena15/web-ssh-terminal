"""SSH가 아닌 터미널 세션: Telnet · Rlogin · Serial(COM). WebSocket /raw.

브라우저와 주고받는 형식은 /ws(SSH)와 같다: 첫 메시지 {"type":"connect", "proto": ...},
이후 바이너리 = 키 입력, {"type":"resize"} = 창 크기. 서버 → 바이너리 출력(UTF-8), connected/closed/error.
Serial은 이 PC의 COM 포트를 여는 기능이라 LOCAL_MODE(127.0.0.1 바인딩)일 때만 허용.
"""
import asyncio
import codecs
import json
import socket
import struct
import threading

from websockets.exceptions import ConnectionClosed

from wst import common
from wst.term import ENCODINGS, SessionLog

# ── Telnet (RFC 854 + ECHO/SGA/NAWS/TTYPE만 협상) ───────────────
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
ECHO, SGA, TTYPE, NAWS = 1, 3, 24, 31


class Telnet:
    def __init__(self, sock):
        self.sock, self.state, self.sb = sock, 0, bytearray()
        self.cols, self.rows, self.naws = 80, 24, False

    def _send(self, *b):
        self.sock.sendall(bytes(b))

    def send_naws(self):
        if self.naws:
            self.sock.sendall(bytes([IAC, SB, NAWS]) + struct.pack(">HH", self.cols, self.rows).replace(b"\xff", b"\xff\xff")
                              + bytes([IAC, SE]))

    def feed(self, data):
        """서버에서 받은 바이트 → 화면에 보낼 바이트 (IAC 명령은 처리하고 뺌)"""
        out = bytearray()
        for b in data:
            st = self.state
            if st == 0:
                if b == IAC:
                    self.state = 1
                else:
                    out.append(b)
            elif st == 1:                                 # IAC 다음
                if b == IAC:
                    out.append(IAC)
                    self.state = 0
                elif b in (DO, DONT, WILL, WONT):
                    self.state, self.cmd = 2, b
                elif b == SB:
                    self.state, self.sb = 3, bytearray()
                else:
                    self.state = 0
            elif st == 2:                                 # 옵션 협상
                self.state = 0
                self._negotiate(self.cmd, b)
            elif st == 3:                                 # 하위 협상 내용
                if b == IAC:
                    self.state = 4
                else:
                    self.sb.append(b)
            elif st == 4:
                if b == SE:
                    self.state = 0
                    if self.sb[:2] == bytes([TTYPE, 1]):  # TTYPE SEND → 터미널 종류 알림
                        self.sock.sendall(bytes([IAC, SB, TTYPE, 0]) + b"XTERM-256COLOR" + bytes([IAC, SE]))
                else:
                    self.sb.append(b)
                    self.state = 3
        return bytes(out)

    def _negotiate(self, cmd, opt):
        if cmd == DO:
            if opt in (SGA, TTYPE, NAWS):
                self._send(IAC, WILL, opt)
                if opt == NAWS:
                    self.naws = True
                    self.send_naws()
            else:
                self._send(IAC, WONT, opt)
        elif cmd == WILL:
            self._send(IAC, DO if opt in (ECHO, SGA) else DONT, opt)
        elif cmd == DONT:
            self._send(IAC, WONT, opt)
        # WONT: 응답 안 함

    def write(self, data):
        self.sock.sendall(data.replace(b"\xff", b"\xff\xff"))

    def resize(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.send_naws()


# ── Serial (Win32 API 직접: 별도 패키지 없이) ───────────────────
def list_com_ports():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
    except OSError:
        return []
    out, i = [], 0
    while True:
        try:
            _, v, _ = winreg.EnumValue(k, i)
        except OSError:
            break
        out.append(v)
        i += 1
    return sorted(out, key=lambda x: (len(x), x))


class Serial:
    def __init__(self, port, baud=9600, bits=8, parity="N", stop=1, flow="none"):
        import ctypes
        import ctypes.wintypes as wt
        self.k = k = ctypes.windll.kernel32
        self.ct, self.wt = ctypes, wt
        k.CreateFileW.restype = wt.HANDLE
        h = k.CreateFileW(f"\\\\.\\{port}", 0xC0000000, 0, None, 3, 0, None)   # GENERIC_READ|WRITE, OPEN_EXISTING
        if h in (None, wt.HANDLE(-1).value):
            err = ctypes.GetLastError()
            raise OSError({2: f"{port}이(가) 없습니다", 5: f"{port}을(를) 다른 프로그램이 쓰고 있습니다"}.get(err, f"{port} 열기 실패 ({err})"))
        self.h = h

        class DCB(ctypes.Structure):
            _fields_ = [("DCBlength", wt.DWORD), ("BaudRate", wt.DWORD), ("flags", wt.DWORD), ("wReserved", wt.WORD),
                        ("XonLim", wt.WORD), ("XoffLim", wt.WORD), ("ByteSize", ctypes.c_ubyte), ("Parity", ctypes.c_ubyte),
                        ("StopBits", ctypes.c_ubyte), ("XonChar", ctypes.c_char), ("XoffChar", ctypes.c_char),
                        ("ErrorChar", ctypes.c_char), ("EofChar", ctypes.c_char), ("EvtChar", ctypes.c_char), ("wReserved1", wt.WORD)]
        d = DCB()
        d.DCBlength = ctypes.sizeof(DCB)
        k.GetCommState(h, ctypes.byref(d))
        d.BaudRate, d.ByteSize = int(baud), int(bits)
        d.Parity = {"N": 0, "O": 1, "E": 2, "M": 3, "S": 4}[parity]
        d.StopBits = {1: 0, 1.5: 1, 2: 2}[float(stop) if float(stop) == 1.5 else int(stop)]
        flags = 0x1                                         # fBinary
        if parity != "N":
            flags |= 0x2                                    # fParity
        if flow == "rtscts":
            flags |= 0x4 | (2 << 12)                        # fOutxCtsFlow, fRtsControl=HANDSHAKE
        else:
            flags |= (1 << 12)                              # fRtsControl=ENABLE
        flags |= (1 << 4)                                   # fDtrControl=ENABLE
        if flow == "xonxoff":
            flags |= 0x100 | 0x200                          # fOutX, fInX
            d.XonChar, d.XoffChar, d.XonLim, d.XoffLim = b"\x11", b"\x13", 2048, 512
        d.flags = flags
        if not k.SetCommState(h, ctypes.byref(d)):
            self.close()
            raise OSError(f"통신 설정을 적용할 수 없습니다 ({baud} {bits}{parity}{stop})")

        class TO(ctypes.Structure):
            _fields_ = [(n, wt.DWORD) for n in ("RI", "RTM", "RTC", "WTM", "WTC")]
        k.SetCommTimeouts(h, ctypes.byref(TO(50, 0, 200, 0, 2000)))   # 읽기: 최대 200ms 기다림

    def read(self):
        buf = self.ct.create_string_buffer(4096)
        n = self.wt.DWORD()
        if not self.k.ReadFile(self.h, buf, 4096, self.ct.byref(n), None):
            raise OSError("포트 읽기 실패 (케이블이 빠졌을 수 있음)")
        return buf.raw[:n.value]

    def write(self, data):
        n = self.wt.DWORD()
        self.k.WriteFile(self.h, data, len(data), self.ct.byref(n), None)

    def send_break(self):
        self.k.SetCommBreak(self.h)
        threading.Timer(0.3, lambda: self.k.ClearCommBreak(self.h)).start()

    def close(self):
        if getattr(self, "h", None):
            self.k.CloseHandle(self.h)
            self.h = None


# ── WebSocket 처리 ──────────────────────────────────────────
async def raw_handler(ws):
    loop = asyncio.get_running_loop()

    async def send_json(**obj):
        await ws.send(json.dumps(obj, ensure_ascii=False))

    try:
        p = json.loads(await asyncio.wait_for(ws.recv(), 30))
        proto = p["proto"]
        assert p.get("type") == "connect" and proto in ("telnet", "rlogin", "serial")
    except Exception:
        await ws.close(1008, "bad connect message")
        return
    if proto == "serial" and not common.LOCAL_MODE:
        await send_json(type="error", message="Serial은 서버가 127.0.0.1로 실행 중일 때만 쓸 수 있습니다")
        await ws.close()
        return
    enc = ENCODINGS.get(p.get("encoding"), "utf-8")
    cols, rows = int(p.get("cols") or 80), int(p.get("rows") or 24)

    gws = []                                          # 게이트웨이 SSH 연결 (끝날 때 닫음)

    def ask_hostkey(host, keytype, fp):              # _open(스레드)에서만 불림 — 이때는 아래 수신 루프가 아직 돌지 않음
        async def _ask():
            await send_json(type="hostkey", host=host, keytype=keytype, fingerprint=fp)
            while True:
                m = await ws.recv()
                if isinstance(m, str):
                    r = json.loads(m)
                    if r.get("type") == "hostkey_reply":
                        return bool(r.get("accept"))
        return asyncio.run_coroutine_threadsafe(_ask(), loop).result(timeout=120)

    def _open():
        if proto == "serial":
            dev = Serial(p["com"], p.get("baud") or 9600, p.get("bits") or 8, p.get("parity") or "N",
                         p.get("stop") or 1, p.get("flow") or "none")
            return dev, dev.read, dev.write, f'{p["com"]} {p.get("baud") or 9600}'
        port = int(p.get("port") or (23 if proto == "telnet" else 513))
        if proto == "rlogin":                         # rlogind는 1023 이하 원본 포트를 요구
            target = common.check_remote_target(p["host"])
            sock = None
            for lp in range(1023, 511, -1):
                try:
                    sock = socket.create_connection((target, port), 10, source_address=("", lp))
                    break
                except OSError as e:
                    if getattr(e, "winerror", None) not in (10048, 10013):
                        raise
            if not sock:
                sock = socket.create_connection((target, port), 10)
            sock.sendall(b"\0" + (p.get("localUser") or p.get("username") or "user").encode() + b"\0"
                         + (p.get("username") or "").encode() + b"\0" + b"xterm-256color/38400\0")
            sock.recv(1)                                # 서버가 보내는 \0 (10초 안에 안 오면 timeout)
            sock.settimeout(None)
            return sock, lambda: sock.recv(65536), sock.sendall, f'{p.get("username", "")}@{p["host"]}:{port}'
        if p.get("gateway"):                          # SSH 게이트웨이 경유: direct-tcpip 채널을 소켓처럼 사용
            from wst.sshconn import open_chain
            gw, gj = open_chain(p["gateway"], ask_hostkey)        # 처음 보는 게이트웨이 키 → 브라우저 확인 창 (SSH 탭과 같음)
            gws.extend([gw, gj])
            sock = gw.get_transport().open_channel("direct-tcpip", (p["host"], port), ("127.0.0.1", 0), timeout=10)
        else:
            target = common.check_remote_target(p["host"])
            sock = socket.create_connection((target, port), 10)
            sock.settimeout(None)                         # 연결 제한 10초가 recv에 남으면 10초 무출력에 끊김
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        t = Telnet(sock)
        t.cols, t.rows = cols, rows

        def rd():
            while True:
                d = sock.recv(65536)
                if not d:
                    return b""
                out = t.feed(d)
                if out:
                    return out
        return t, rd, t.write, f'{p["host"]}:{port}'

    try:
        dev, rd, wr, target = await asyncio.to_thread(_open)
    except Exception as e:
        from wst.sshconn import describe
        msg, code = describe(e) if gws or p.get("gateway") or "paramiko" in type(e).__module__ else (f"접속 실패: {getattr(e, 'strerror', None) or e}", None)
        for c in gws:
            if c:
                c.close()
        if code and p.get("gateway"):                               # 게이트웨이 홉의 오류임을 표시 (gateway / gatewayjump)
            code = code.replace(":target", ":gateway").replace(":jump", ":gatewayjump")
        await send_json(type="error", message=msg, code=code)
        await ws.close()
        return

    log = None
    if (p.get("log") or {}).get("on"):
        try:
            log = SessionLog(p["log"].get("name") or target, f"{proto}:{target}", bool(p["log"].get("ts")))
        except OSError as e:
            await send_json(type="notice", message=f"로그 파일을 만들 수 없습니다: {e}")
    await send_json(type="connected", sid=None, log=str(log.path) if log else None)
    stop = threading.Event()

    def pump():
        dec = codecs.getincrementaldecoder(enc)("replace")
        dropped = False
        try:
            while not stop.is_set():
                data = rd()
                if not data:
                    if proto == "serial":
                        continue                            # 시리얼은 읽을 게 없으면 빈 값 → 계속 기다림
                    break                                   # 원격이 정상적으로 닫음 (logout/exit)
                text = dec.decode(data)
                if log:
                    log.write(text)
                asyncio.run_coroutine_threadsafe(ws.send(text.encode("utf-8")), loop).result()
        except Exception:
            dropped = True

        async def _end():
            try:
                # 원격이 정상적으로 닫으면(텔넷 logout) exit 0 → 자동 재접속 안 함, 오류로 끊기면 재접속 대상
                await send_json(type="closed", exit=None if dropped else 0)
                await ws.close()
            except ConnectionClosed:
                pass
        if not stop.is_set():
            asyncio.run_coroutine_threadsafe(_end(), loop)

    threading.Thread(target=pump, daemon=True).start()
    in_dec = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        async for msg in ws:
            if isinstance(msg, bytes):
                if enc != "utf-8":
                    msg = in_dec.decode(msg).encode(enc, "replace")
                if proto == "serial" and p.get("crlf") and msg == b"\r":
                    msg = b"\r\n"
                await asyncio.to_thread(wr, msg)
            else:
                m = json.loads(msg)
                if m.get("type") == "resize" and proto == "telnet":
                    await asyncio.to_thread(dev.resize, int(m["cols"]), int(m["rows"]))
                elif m.get("type") == "break" and proto == "serial":
                    dev.send_break()
    except ConnectionClosed:
        pass
    finally:
        stop.set()
        try:
            (dev.sock if proto == "telnet" else dev).close()
        except Exception:
            pass
        for c in gws:
            if c:
                c.close()
        if log:
            log.close()
