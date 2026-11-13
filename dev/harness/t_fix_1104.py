"""2026-11-04 잔여 항목 시험 (#1 게이트웨이 RDP 주소·자격 증명 분리, #15 틀린 키 암호, #17 터널 중지 경쟁).
실행: WEBSSH_DATA=<임시 폴더> python dev/harness/t_fix_1104.py <키 폴더>   (가짜 sshd 2222가 떠 있어야 함)
<키 폴더>: ssh-keygen -N right 로 만든 k_ed25519·k_ecdsa·k_rsa·k_rsapem (암호 right)"""
import ctypes
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from wst import api
from wst import sshconn
from wst import tunnels
from wst import vault

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def ask_yes(*_):
    return True


GW = {"id": "gw", "host": "127.0.0.1", "port": 2222, "username": "test", "auth": "password"}
SEC = {"password": "pw"}

# ── #15 틀린 키 암호 → 다시 묻기(passphrase 코드) ──
kdir = sys.argv[1]
for f in ("k_ed25519", "k_ecdsa", "k_rsa", "k_rsapem"):
    text = open(os.path.join(kdir, f), encoding="utf-8").read()
    try:
        sshconn._load_pkey(text, "wrong")
        check(f"#15 {f} 틀린 암호", False, "예외 없음")
    except Exception as e:
        msg, code = sshconn.describe(e)
        check(f"#15 {f} 틀린 암호", code == "passphrase:target" and "틀렸" in msg, f"{code} / {msg}")
    check(f"#15 {f} 맞는 암호", sshconn._load_pkey(text, "right") is not None)
    try:
        sshconn._load_pkey("garbage\n", "x")
        check("#15 깨진 키", False)
    except ValueError:
        pass
check("#15 깨진 키는 암호 재질문 아님(ValueError)", True)

# ── #17 바인드 직후 중지가 들어와도 다시 켜지지 않음 ──
real_socket = socket.socket


class StopOnListen(real_socket):
    target = None

    def listen(self, n):
        super().listen(n)
        StopOnListen.target.stop()                    # 바인드와 "켜짐" 사이에 중지 버튼


tunnels.socket.socket = StopOnListen
mgr = tunnels.TunnelManager()
t = tunnels.Tunnel("race", {"type": "local", "listenPort": 0, "destHost": "127.0.0.1", "destPort": 9}, api.ssh_params(GW, SEC, [GW]),
                   lambda *a: None, ask_yes)
StopOnListen.target = t
try:
    t.start()
    stop_err = None
except ValueError as e:                               # E2: 시작 중 중지되면 "중지" 예외
    stop_err = e
tunnels.socket.socket = real_socket
check("#17 중지 경쟁: 시작이 '중지' 예외로 끝남", stop_err is not None and "중지" in str(stop_err), repr(stop_err))
check("#17 중지 경쟁: 상태 off 유지", t.state == "off", t.state)
check("#17 중지 경쟁: 리슨 소켓 없음", t.listener is None and t.client is None)

# ── #1 게이트웨이 RDP: 세션마다 다른 루프백 주소, 자격 증명도 주소별 ──
echo = real_socket()
echo.bind(("127.0.0.1", 0))
echo.listen(4)
EPORT = echo.getsockname()[1]


def echo_loop():
    while True:
        c, _ = echo.accept()
        c.sendall(c.recv(100))
        time.sleep(0.3)                               # 바로 닫으면 Windows가 RST를 보내 응답이 전달되기 전에 끊김
        c.close()


threading.Thread(target=echo_loop, daemon=True).start()

creds = []                                            # (동작, 주소, 비밀번호)
api.vault.write_rdp_cred = lambda h, u, p: creds.append(("write", h, p))
api.vault.delete_rdp_cred = lambda h: creds.append(("delete", h, None))


class StubVault:
    def get(self, key):
        return {"password": "pw-" + key.split("@")[0]}          # rdp:ua@… → 세션(사용자)마다 다른 비밀번호


api.vault.VAULT = StubVault()
procs = {}


class FakeMstsc:                                      # mstsc 대신: 창이 열려 있는 동안 wait()가 막힘
    def __init__(self, args):
        self.args, self.done = args, threading.Event()
        address = next((arg[3:] for arg in args if arg.startswith("/v:")), None)
        if address is None:
            address = open(args[1], encoding="utf-16").read().split("full address:s:")[1].split()[0]
        procs[address] = self

    def wait(self):
        self.done.wait()


api.subprocess.Popen = FakeMstsc
data = {"sessions": [GW]}
A = {"id": "rdpA", "name": "A", "host": "127.0.0.1", "port": EPORT, "gateway": "gw", "username": "ua"}
B = {"id": "rdpB", "name": "B", "host": "127.0.0.1", "port": EPORT, "gateway": "gw", "username": "ub"}
api.ssh_params = lambda s, sec, sessions=None: {**{k: s[k] for k in ("host", "port", "username")}, "password": "pw"}
addrA = api._launch_rdp(A, data, SEC, ask_yes)
addrB = api._launch_rdp(B, data, SEC, ask_yes)
hA, hB = addrA.rsplit(":", 1)[0], addrB.rsplit(":", 1)[0]
check("#1 A·B 주소가 다르고 127.77.x.y", hA != hB and hA.startswith("127.77.") and hB.startswith("127.77."), f"{addrA} {addrB}")
for addr in (addrA, addrB):
    h, p = addr.rsplit(":", 1)
    s = socket.create_connection((h, int(p)), 5)
    s.sendall(b"ping")
    check(f"#1 터널 {addr} → 대상 전달", s.recv(10) == b"ping")
    s.close()
writes = [(h, p) for op, h, p in creds if op == "write"]
check("#1 자격 증명이 각자 주소에", len(writes) == 2 and writes[0][0] == hA and writes[1][0] == hB and writes[0][1] != writes[1][1], str(writes))
addrA2 = api._launch_rdp(A, data, SEC, ask_yes)           # 같은 세션 두 번째 창
check("#1 같은 세션은 같은 주소", addrA2 == addrA)
n = len(creds)
procs[addrA].done.set()                              # A의 첫 창 닫음 (procs는 주소별 마지막 창이라 두 번째 창 핸들)
time.sleep(0.3)
check("#1 A 창이 남아 있으면 자격 증명 유지", not any(op == "delete" and h == hA for op, h, _ in creds[n:]), str(creds[n:]))
procs[addrB].done.set()
time.sleep(0.3)
check("#1 B 닫으면 B 주소만 삭제", ("delete", hB, None) in creds[n:] and ("delete", hA, None) not in creds[n:], str(creds[n:]))
time.sleep(11.5)                                     # 주소는 터널 정리(연결 없음 10초)까지 예약됨 (D2)
check("#1 B 주소는 터널 정리 후 반환", "rdpB" not in api._rdp_addrs and "rdpA" in api._rdp_addrs, str(api._rdp_addrs))

# 루프백이 아닌 bindHost 거부
try:
    tunnels.Tunnel("bad", {"type": "local", "bindHost": "0.0.0.0", "listenPort": 0, "destHost": "x", "destPort": 1},
                   {"host": "127.0.0.1", "port": 2222, "username": "test", "password": "pw"}, lambda *a: None, ask_yes).start()
    check("#1 0.0.0.0 바인드 거부", False)
except RuntimeError as e:
    check("#1 0.0.0.0 바인드 거부", True, str(e))

# 실제 Windows 자격 증명: 127.77 주소에 쓰고 읽고 지우기
import importlib
importlib.reload(vault)                              # 위에서 바꿔 둔 write/delete를 원래 함수로
vault.write_rdp_cred("127.77.250.250", "t", "dummy")
pc = ctypes.c_void_p()
ok = ctypes.windll.advapi32.CredReadW("TERMSRV/127.77.250.250", 2, 0, ctypes.byref(pc))
if ok:
    ctypes.windll.advapi32.CredFree(pc)
vault.delete_rdp_cred("127.77.250.250")
gone = not ctypes.windll.advapi32.CredReadW("TERMSRV/127.77.250.250", 2, 0, ctypes.byref(pc))
check("#1 실제 CredWrite/Read/Delete (TERMSRV/127.77.250.250)", bool(ok) and gone)

print(f"\n{sum(results)}/{len(results)} 통과")
os._exit(0 if all(results) else 1)
