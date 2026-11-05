"""E1·E2·E3·E4·E5·E8a 시험:
- E1: 설정(연결 대상)이 바뀐 세션이 옛 터널을 재사용하지 않고 새 대상으로 연결(TunnelManager.start 및 api._launch_rdp), 같은 대상이면 기존 터널 재사용
- E2: 시작(_connect) 중 stop()된 터널이 접속에 성공해도 '중지' 예외를 내고 off 유지, _launch_rdp도 예외를 올리고 mstsc 미실행·자격 증명 정리
- E3: 열린 창이 닫힌 뒤 진행 중이던 마지막 실행이 실패로 끝나면 해당 주소의 자격 증명도 삭제
- E4: 열린 창이 없는 상태에서 동시에 시작된 첫 실행들이 첫 write/mstsc 전에 delete_rdp_cred를 최소 1회 수행(창이 열려 있을 때 추가 실행은 미삭제)
- E5: 포워딩 연결이 열린 채 stop() 후 연결이 닫혀도 off 알림 뒤에 state!='off' 또는 conns!=0 알림이 오지 않으며 status()의 conns도 0
- E8a: 같은 tid 터널이 시작 중(starting)일 때 두 번째 TunnelManager.start 호출 시 대기 후 같은 숫자 포트 터널 반환
실행: WEBSSH_DATA=<임시 폴더> python -u dev/harness/t_e18.py   (가짜 sshd 2222가 떠 있어야 함)"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from wst import api
from wst import tunnels

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def ask_yes(*_):
    return True


GW = {"id": "gw", "host": "127.0.0.1", "port": 2222, "username": "test", "auth": "password"}
SEC = {"password": "pw"}


def start_tagged_echo_server(tag, hold_event=None):
    """접속 시 받은 데이터 앞에 tag 바이트열을 붙여 돌려주는 에코 서버.
    hold_event가 주어지면 응답 후 hold_event가 설정될 때까지 연결을 열어 둔다."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    stop_evt = threading.Event()

    def loop():
        while not stop_evt.is_set():
            try:
                c, _ = srv.accept()
            except OSError:
                break

            def handle(conn):
                try:
                    data = conn.recv(100)
                    if data:
                        conn.sendall(tag + b":" + data)
                    if hold_event is not None:
                        hold_event.wait(10.0)
                    else:
                        time.sleep(0.2)
                except OSError:
                    pass
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass

            threading.Thread(target=handle, args=(c,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv, srv.getsockname()[1], stop_evt


def query_addr(addr, payload=b"ping", timeout=5.0):
    host, port_s = addr.rsplit(":", 1)
    with socket.create_connection((host, int(port_s)), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(payload)
        return s.recv(100)


def parse_rdp_full_address(rdp_path):
    for enc in ("utf-16", "utf-8"):
        try:
            txt = open(rdp_path, encoding=enc).read()
            if "full address:s:" in txt:
                return txt.split("full address:s:", 1)[1].splitlines()[0].strip()
        except Exception:
            continue
    return ""


# ── E1: 설정이 바뀐 세션이 옛 터널을 재사용하면 안 됨 ──
def test_e1(port_a, port_b):
    # 1) TunnelManager.start 직접 경로
    mgr = tunnels.TunnelManager()
    params1 = {"host": "127.0.0.1", "port": 2222, "username": "test", "password": "pw"}
    params1_pw2 = {"host": "127.0.0.1", "port": 2222, "username": "test", "password": "pw"}
    cfg_a = {"type": "local", "listenPort": 0, "destHost": "127.0.0.1", "destPort": port_a}
    cfg_b = {"type": "local", "listenPort": 0, "destHost": "127.0.0.1", "destPort": port_b}

    try:
        t1 = mgr.start("e1_direct", cfg_a, params1, ask_yes) or mgr.tunnels.get("e1_direct")
        p1 = getattr(t1, "port", None)
        r1 = query_addr(f"127.0.0.1:{p1}") if p1 else b""

        # 같은 대상(listenPort=0)으로 다시 호출하면 기존 터널(같은 포트)을 돌려줘야 함
        t_same = mgr.start("e1_direct", dict(cfg_a), params1_pw2, ask_yes) or mgr.tunnels.get("e1_direct")
        p_same = getattr(t_same, "port", None)
        r_same = query_addr(f"127.0.0.1:{p_same}") if p_same else b""

        # 같은 tid로 대상을 port_b로 바꿔 호출하면 옛 터널을 중지하고 새 대상으로 열어야 함
        t2 = mgr.start("e1_direct", cfg_b, params1, ask_yes) or mgr.tunnels.get("e1_direct")
        p2 = getattr(t2, "port", None)
        r2 = query_addr(f"127.0.0.1:{p2}") if p2 else b""

        ok_direct = (
            isinstance(p1, int)
            and p1 > 0
            and r1 == b"A:ping"
            and p_same == p1
            and r_same == b"A:ping"
            and isinstance(p2, int)
            and p2 > 0
            and r2 == b"B:ping"
            and getattr(t1, "state", None) == "off"
        )
        check(
            "E1-1 TunnelManager.start 같은 대상은 기존 포트 재사용, 다른 대상은 새 대상으로 재연결",
            ok_direct,
            f"p1={p1}(r={r1}), p_same={p_same}(r={r_same}), p2={p2}(r={r2}), old_state={getattr(t1, 'state', None)}",
        )
    except Exception as e:
        check("E1-1 TunnelManager.start 같은 대상은 기존 포트 재사용, 다른 대상은 새 대상으로 재연결", False, repr(e))
    finally:
        try:
            mgr.stop("e1_direct")
        except Exception:
            pass

    # 2) 게이트웨이 RDP(api._launch_rdp) 경로: 창 닫은 직후(10초 유지 중) 대상 변경 & 창 열린 상태 대상 변경
    orig_popen = api.subprocess.Popen
    orig_ssh_params = api.ssh_params
    orig_write_cred = api.vault.write_rdp_cred
    orig_delete_cred = api.vault.delete_rdp_cred
    orig_vault = api.vault.VAULT

    creds = []
    cred_lock = threading.Lock()
    spawned = []

    def rec_write(h, u, p):
        with cred_lock:
            creds.append(("write", h, u, p))

    def rec_delete(h):
        with cred_lock:
            creds.append(("delete", h, None, None))

    class StubVault:
        def get(self, key):
            return {"password": "pw-" + key}

    class FakeMstsc:
        def __init__(self, args):
            self.args = args
            self.done = threading.Event()
            self.full_address = parse_rdp_full_address(args[1]) if len(args) > 1 else ""
            with cred_lock:
                spawned.append(self)

        def wait(self):
            self.done.wait()

    api.vault.write_rdp_cred = rec_write
    api.vault.delete_rdp_cred = rec_delete
    api.vault.VAULT = StubVault()
    api.subprocess.Popen = FakeMstsc
    api.ssh_params = lambda s, sec, sessions=None: {
        "host": s["host"],
        "port": s["port"],
        "username": s["username"],
        "password": "pw",
    }

    data = {"sessions": [GW]}
    s_a = {"id": "e1_rdp", "name": "E1", "host": "127.0.0.1", "port": port_a, "gateway": "gw", "username": "ua"}
    s_b = {"id": "e1_rdp", "name": "E1", "host": "127.0.0.1", "port": port_b, "gateway": "gw", "username": "ub"}

    try:
        # (a) 창을 닫은 뒤 10초 터널 유지 시간 안에 대상을 A → B로 바꿔 다시 열기
        addr1 = api._launch_rdp(s_a, data, SEC, ask_yes)
        proc1 = spawned[-1]
        resp1 = query_addr(addr1)
        proc1.done.set()
        time.sleep(0.3)

        addr2 = api._launch_rdp(s_b, data, SEC, ask_yes)
        proc2 = spawned[-1]
        resp2 = query_addr(addr2)

        # (b) 창(proc2)이 열려 있는 상태에서 대상을 B → A로 바꿔 다시 열기
        addr3 = api._launch_rdp(s_a, data, SEC, ask_yes)
        proc3 = spawned[-1]
        resp3 = query_addr(addr3)

        ok_rdp = resp1 == b"A:ping" and resp2 == b"B:ping" and resp3 == b"A:ping"
        check(
            "E1-2 _launch_rdp 같은 세션의 대상 변경 시(10초 대기 중 및 창 열림 중) 새 대상 응답 수신",
            ok_rdp,
            f"addr1={addr1}({resp1}), addr2={addr2}({resp2}), addr3={addr3}({resp3})",
        )
    except Exception as e:
        check("E1-2 _launch_rdp 같은 세션의 대상 변경 시(10초 대기 중 및 창 열림 중) 새 대상 응답 수신", False, repr(e))
    finally:
        for p in spawned:
            p.done.set()
        try:
            api.manager.stop("rdp-e1_rdp")
        except Exception:
            pass
        api.subprocess.Popen = orig_popen
        api.ssh_params = orig_ssh_params
        api.vault.write_rdp_cred = orig_write_cred
        api.vault.delete_rdp_cred = orig_delete_cred
        api.vault.VAULT = orig_vault


# ── E2: 시작 중 중지된 터널은 "성공"으로 끝나면 안 됨 ──
def test_e2(port_a):
    orig_connect = tunnels.Tunnel._connect
    cfg = {"type": "local", "listenPort": 0, "destHost": "127.0.0.1", "destPort": port_a}
    params = {"host": "127.0.0.1", "port": 2222, "username": "test", "password": "pw"}

    # 1) TunnelManager.start 직접 호출 중 stop() → 접속은 성공해도 start()는 "중지" 예외를 내야 함
    mgr = tunnels.TunnelManager()
    entered = threading.Event()
    stopped = threading.Event()

    def connect_then_succeed_after_stop(self):
        entered.set()
        stopped.wait(5.0)
        return orig_connect(self)

    tunnels.Tunnel._connect = connect_then_succeed_after_stop
    start_res = [None]
    start_err = [None]

    def run_start():
        try:
            start_res[0] = mgr.start("e2_tun", cfg, params, ask_yes)
        except Exception as e:
            start_err[0] = e

    try:
        th = threading.Thread(target=run_start, daemon=True)
        th.start()
        assert entered.wait(5.0), "E2-1 _connect 진입 실패"
        mgr.stop("e2_tun")
        stopped.set()
        th.join(timeout=5.0)

        t = mgr.tunnels.get("e2_tun")
        err = start_err[0]
        ok_e2_1 = (
            err is not None
            and "중지" in str(err)
            and start_res[0] is None
            and (t is None or t.state == "off")
        )
        check(
            "E2-1 접속 중 stop() 후 접속 성공 시 TunnelManager.start가 '중지' 예외 발생 및 off 유지",
            ok_e2_1,
            f"err={err!r}, res={start_res[0]!r}, state={getattr(t, 'state', None)}",
        )
    finally:
        tunnels.Tunnel._connect = orig_connect
        try:
            mgr.stop("e2_tun")
        except Exception:
            pass

    # 2) _launch_rdp 실행 중 터널 stop() → 예외 전파, mstsc 미실행, 자격 증명 남지 않음
    orig_popen = api.subprocess.Popen
    orig_ssh_params = api.ssh_params
    orig_write_cred = api.vault.write_rdp_cred
    orig_delete_cred = api.vault.delete_rdp_cred
    orig_vault = api.vault.VAULT

    creds = []
    spawned = []
    entered_rdp = threading.Event()
    stopped_rdp = threading.Event()

    def rec_write(h, u, p):
        creds.append(("write", h, p))

    def rec_delete(h):
        creds.append(("delete", h, None))

    class StubVault:
        def get(self, key):
            return {"password": "pw-e2"}

    class FakeMstsc:
        def __init__(self, args):
            self.args = args
            self.done = threading.Event()
            spawned.append(self)

        def wait(self):
            self.done.wait()

    def connect_rdp_succeed_after_stop(self):
        entered_rdp.set()
        stopped_rdp.wait(5.0)
        return orig_connect(self)

    api.vault.write_rdp_cred = rec_write
    api.vault.delete_rdp_cred = rec_delete
    api.vault.VAULT = StubVault()
    api.subprocess.Popen = FakeMstsc
    api.ssh_params = lambda s, sec, sessions=None: {
        "host": s["host"],
        "port": s["port"],
        "username": s["username"],
        "password": "pw",
    }
    tunnels.Tunnel._connect = connect_rdp_succeed_after_stop

    s_e2 = {"id": "e2_rdp", "name": "E2", "host": "127.0.0.1", "port": port_a, "gateway": "gw", "username": "ue2"}
    data = {"sessions": [GW]}
    rdp_out = [None]
    rdp_err = [None]

    def run_rdp():
        try:
            rdp_out[0] = api._launch_rdp(s_e2, data, SEC, ask_yes)
        except Exception as e:
            rdp_err[0] = e

    try:
        th = threading.Thread(target=run_rdp, daemon=True)
        th.start()
        assert entered_rdp.wait(5.0), "E2-2 _connect 진입 실패"
        api.manager.stop("rdp-e2_rdp")
        stopped_rdp.set()
        th.join(timeout=5.0)

        # 자격 증명이 애초에 쓰이지 않았거나, 쓰였다면 마지막 동작이 delete여야 함
        active_creds = set()
        for op, h, _ in creds:
            if op == "write":
                active_creds.add(h)
            elif op == "delete":
                active_creds.discard(h)

        err = rdp_err[0]
        ok_e2_2 = (
            err is not None
            and "중지" in str(err)
            and rdp_out[0] is None
            and len(spawned) == 0
            and len(active_creds) == 0
        )
        check(
            "E2-2 _launch_rdp 터널 접속 중 stop() 시 예외 발생·mstsc 미실행·자격 증명 미잔류",
            ok_e2_2,
            f"err={err!r}, out={rdp_out[0]!r}, spawned={len(spawned)}, creds={creds}",
        )
    finally:
        tunnels.Tunnel._connect = orig_connect
        for p in spawned:
            p.done.set()
        try:
            api.manager.stop("rdp-e2_rdp")
        except Exception:
            pass
        api.subprocess.Popen = orig_popen
        api.ssh_params = orig_ssh_params
        api.vault.write_rdp_cred = orig_write_cred
        api.vault.delete_rdp_cred = orig_delete_cred
        api.vault.VAULT = orig_vault


# ── E3: 실패한 실행이 마지막이면 자격 증명도 지움 ──
def test_e3(port_a, port_b):
    orig_popen = api.subprocess.Popen
    orig_ssh_params = api.ssh_params
    orig_write_cred = api.vault.write_rdp_cred
    orig_delete_cred = api.vault.delete_rdp_cred
    orig_vault = api.vault.VAULT
    orig_connect = tunnels.Tunnel._connect

    creds = []
    cred_lock = threading.Lock()
    spawned = []

    def rec_write(h, u, p):
        with cred_lock:
            creds.append(("write", h, p))

    def rec_delete(h):
        with cred_lock:
            creds.append(("delete", h, None))

    class StubVault:
        def get(self, key):
            return {"password": "pw-e3"}

    class FakeMstsc:
        def __init__(self, args):
            self.args = args
            self.done = threading.Event()
            with cred_lock:
                spawned.append(self)

        def wait(self):
            self.done.wait()

    api.vault.write_rdp_cred = rec_write
    api.vault.delete_rdp_cred = rec_delete
    api.vault.VAULT = StubVault()
    api.subprocess.Popen = FakeMstsc
    api.ssh_params = lambda s, sec, sessions=None: {
        "host": s["host"],
        "port": s["port"],
        "username": s["username"],
        "password": "pw",
    }

    data = {"sessions": [GW]}
    s1 = {"id": "e3_rdp", "name": "E3", "host": "127.0.0.1", "port": port_a, "gateway": "gw", "username": "ue3"}
    # 두 번째 실행이 터널 _connect를 거치도록 기존 터널을 끊거나 대상을 변경
    s2 = {"id": "e3_rdp", "name": "E3", "host": "127.0.0.1", "port": port_b, "gateway": "gw", "username": "ue3"}

    entered_2 = threading.Event()
    release_2 = threading.Event()

    try:
        # 실행 1: 정상적으로 창 1 열림
        addr1 = api._launch_rdp(s1, data, SEC, ask_yes)
        host1 = addr1.rsplit(":", 1)[0]
        proc1 = spawned[-1]

        # 실행 2가 터널 단계(_connect)에서 대기 후 실패하도록 설정
        # (E1과 독립적으로도 터널 단계 진입을 보장하기 위해 기존 터널도 미리 stop)
        api.manager.stop("rdp-e3_rdp")

        def fail_connect(self):
            entered_2.set()
            release_2.wait(5.0)
            raise RuntimeError("E3 simulated tunnel failure")

        tunnels.Tunnel._connect = fail_connect
        err2 = [None]

        def run_launch2():
            try:
                api._launch_rdp(s2, data, SEC, ask_yes)
            except Exception as e:
                err2[0] = e

        th2 = threading.Thread(target=run_launch2, daemon=True)
        th2.start()
        assert entered_2.wait(5.0), "E3 실행 2 _connect 진입 실패"

        # 실행 2가 진행 중인 상태에서 창 1이 닫힘
        proc1.done.set()
        time.sleep(0.4)

        # 이제 마지막 남은 실행 2가 터널 단계에서 실패로 끝남
        release_2.set()
        th2.join(timeout=5.0)
        time.sleep(0.3)

        host_ops = [op for op, h, _ in creds if h == host1]
        ok_e3 = (
            err2[0] is not None
            and "write" in host_ops
            and bool(host_ops)
            and host_ops[-1] == "delete"
        )
        check(
            "E3 창 1 종료 후 마지막 실행 2가 터널 단계에서 실패하면 해당 주소의 자격 증명도 삭제",
            ok_e3,
            f"err2={err2[0]!r}, host={host1}, ops={host_ops}, creds={creds}",
        )
    finally:
        tunnels.Tunnel._connect = orig_connect
        for p in spawned:
            p.done.set()
        try:
            api.manager.stop("rdp-e3_rdp")
        except Exception:
            pass
        api.subprocess.Popen = orig_popen
        api.ssh_params = orig_ssh_params
        api.vault.write_rdp_cred = orig_write_cred
        api.vault.delete_rdp_cred = orig_delete_cred
        api.vault.VAULT = orig_vault


# ── E4: 동시에 시작된 첫 실행들도 남은 자격 증명을 지움 ──
def test_e4(port_a):
    orig_popen = api.subprocess.Popen
    orig_ssh_params = api.ssh_params
    orig_write_cred = api.vault.write_rdp_cred
    orig_delete_cred = api.vault.delete_rdp_cred
    orig_vault = api.vault.VAULT
    orig_connect = tunnels.Tunnel._connect

    events = []
    ev_lock = threading.Lock()
    spawned = []

    def rec_write(h, u, p):
        with ev_lock:
            events.append(("write", h))

    def rec_delete(h):
        with ev_lock:
            events.append(("delete", h))

    class StubVault:
        def get(self, key):
            return {"password": "pw-e4"}

    class FakeMstsc:
        def __init__(self, args):
            self.args = args
            self.done = threading.Event()
            addr = parse_rdp_full_address(args[1]) if len(args) > 1 else ""
            h = addr.rsplit(":", 1)[0] if ":" in addr else addr
            with ev_lock:
                events.append(("mstsc", h))
                spawned.append(self)

        def wait(self):
            self.done.wait()

    def slow_connect(self):
        time.sleep(0.8)
        return orig_connect(self)

    api.vault.write_rdp_cred = rec_write
    api.vault.delete_rdp_cred = rec_delete
    api.vault.VAULT = StubVault()
    api.subprocess.Popen = FakeMstsc
    api.ssh_params = lambda s, sec, sessions=None: {
        "host": s["host"],
        "port": s["port"],
        "username": s["username"],
        "password": "pw",
    }
    tunnels.Tunnel._connect = slow_connect

    data = {"sessions": [GW]}
    s_e4 = {"id": "e4_rdp", "name": "E4", "host": "127.0.0.1", "port": port_a, "gateway": "gw", "username": "ue4"}
    outs = [None, None]
    errs = [None, None]

    def call_rdp(idx):
        try:
            outs[idx] = api._launch_rdp(s_e4, data, SEC, ask_yes)
        except Exception as e:
            errs[idx] = e

    try:
        # 두 첫 실행을 거의 동시에 시작 (둘 다 터널 연결 전에 주소 예약 진입)
        t1 = threading.Thread(target=call_rdp, args=(0,), daemon=True)
        t2 = threading.Thread(target=call_rdp, args=(1,), daemon=True)
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

        addr = outs[0] or outs[1] or ""
        host = addr.rsplit(":", 1)[0] if ":" in addr else ""
        host_ops = [op for op, h in events if h == host]

        # 첫 write(및 첫 mstsc) 전에 delete가 최소 1번 있어야 함
        first_write_or_mstsc = next(
            (i for i, op in enumerate(host_ops) if op in ("write", "mstsc")),
            len(host_ops),
        )
        deleted_before_first_write = "delete" in host_ops[:first_write_or_mstsc]

        # 이미 창이 열려 있는 상태에서 추가 실행 시에는 delete를 호출하지 않아야 함 (D2-1 유지)
        idx_after_open = len(events)
        tunnels.Tunnel._connect = orig_connect
        api._launch_rdp(s_e4, data, SEC, ask_yes)
        extra_ops = [op for op, h in events[idx_after_open:] if h == host]
        no_delete_while_open = "delete" not in extra_ops

        ok_e4 = (
            bool(host)
            and deleted_before_first_write
            and no_delete_while_open
        )
        check(
            "E4 동시 시작된 두 첫 실행에서 첫 write/mstsc 전에 delete 최소 1회 수행 및 창 열림 중 추가 실행 미삭제",
            ok_e4,
            f"host={host}, ops={host_ops}, extra_ops={extra_ops}, errs={errs}",
        )
    finally:
        tunnels.Tunnel._connect = orig_connect
        for p in spawned:
            p.done.set()
        try:
            api.manager.stop("rdp-e4_rdp")
        except Exception:
            pass
        api.subprocess.Popen = orig_popen
        api.ssh_params = orig_ssh_params
        api.vault.write_rdp_cred = orig_write_cred
        api.vault.delete_rdp_cred = orig_delete_cred
        api.vault.VAULT = orig_vault


# ── E5: 중지 뒤에는 연결 수 알림도 없음 ──
def test_e5():
    hold_evt = threading.Event()
    srv, port_hold, stop_evt = start_tagged_echo_server(b"E5", hold_event=hold_evt)
    mgr = tunnels.TunnelManager()
    cfg = {"type": "local", "listenPort": 0, "destHost": "127.0.0.1", "destPort": port_hold}
    params = {"host": "127.0.0.1", "port": 2222, "username": "test", "password": "pw"}

    notifications = []
    notif_lock = threading.Lock()

    def on_notify(*args):
        t = mgr.tunnels.get("e5_tun")
        if t is None:
            return
        st = getattr(t, "state", None)
        cn = getattr(t, "conns", None)
        try:
            st_dict = t.status()
            if isinstance(st_dict, dict):
                st = st_dict.get("state", st)
                cn = st_dict.get("conns", cn)
        except Exception:
            pass
        for a in args:
            if isinstance(a, dict) and a.get("id") in (None, "e5_tun"):
                st = a.get("state", st)
                cn = a.get("conns", cn)
        with notif_lock:
            notifications.append((st, cn))

    mgr.listeners.append(on_notify)
    cli_sock = None
    try:
        t = mgr.start("e5_tun", cfg, params, ask_yes) or mgr.tunnels["e5_tun"]
        cli_sock = socket.create_connection(("127.0.0.1", t.port), timeout=5.0)
        cli_sock.settimeout(5.0)
        cli_sock.sendall(b"hello")
        data = cli_sock.recv(20)
        time.sleep(0.2)

        # 포워딩 연결이 열려 있는 채로 stop() 호출
        mgr.stop("e5_tun")

        # stop() 이후에 포워딩 연결 종료 유도
        hold_evt.set()
        try:
            cli_sock.close()
        except Exception:
            pass
        cli_sock = None
        time.sleep(0.5)

        with notif_lock:
            snap = list(notifications)

        off_indices = [i for i, (st, _) in enumerate(snap) if st == "off"]
        after_off = snap[off_indices[0] :] if off_indices else [("missing_off", -1)]
        status_after = t.status() if hasattr(t, "status") else {"state": t.state, "conns": t.conns}

        ok_e5 = (
            data == b"E5:hello"
            and bool(off_indices)
            and all(st == "off" and cn == 0 for st, cn in after_off)
            and getattr(t, "state", None) == "off"
            and getattr(t, "conns", None) == 0
            and status_after.get("conns", -1) == 0
        )
        check(
            "E5 포워딩 연결 열림 상태에서 stop() 후 off 알림 뒤 state=='off'·conns==0 유지",
            ok_e5,
            f"notifications={snap}, status_after={status_after}",
        )
    except Exception as e:
        check("E5 포워딩 연결 열림 상태에서 stop() 후 off 알림 뒤 state=='off'·conns==0 유지", False, repr(e))
    finally:
        hold_evt.set()
        if cli_sock is not None:
            try:
                cli_sock.close()
            except Exception:
                pass
        try:
            mgr.stop("e5_tun")
        except Exception:
            pass
        stop_evt.set()
        try:
            srv.close()
        except Exception:
            pass


# ── E8a: 시작 중(starting) 두 번째 TunnelManager.start가 같은 숫자 포트 터널 반환 ──
def test_e8a(port_a):
    orig_connect = tunnels.Tunnel._connect
    mgr = tunnels.TunnelManager()
    cfg = {"type": "local", "listenPort": 0, "destHost": "127.0.0.1", "destPort": port_a}
    params = {"host": "127.0.0.1", "port": 2222, "username": "test", "password": "pw"}

    entered = threading.Event()

    def slow_connect(self):
        entered.set()
        time.sleep(1.0)
        return orig_connect(self)

    tunnels.Tunnel._connect = slow_connect
    res = [None, None]
    err = [None, None]

    def call_start(i):
        try:
            res[i] = mgr.start("e8a_tun", cfg, params, ask_yes) or mgr.tunnels.get("e8a_tun")
        except Exception as e:
            err[i] = e

    try:
        th1 = threading.Thread(target=call_start, args=(0,), daemon=True)
        th2 = threading.Thread(target=call_start, args=(1,), daemon=True)
        th1.start()
        assert entered.wait(5.0), "E8a 첫 start _connect 진입 실패"
        time.sleep(0.15)
        th2.start()
        th1.join(timeout=10.0)
        th2.join(timeout=10.0)

        p0 = getattr(res[0], "port", None)
        p1 = getattr(res[1], "port", None)
        echo_ok = False
        if isinstance(p0, int) and p0 > 0:
            try:
                echo_ok = query_addr(f"127.0.0.1:{p0}") == b"A:ping"
            except Exception:
                echo_ok = False

        ok_e8a = (
            err[0] is None
            and err[1] is None
            and isinstance(p0, int)
            and p0 > 0
            and p0 == p1
            and echo_ok
        )
        check(
            "E8a 시작 중(starting) 두 번째 TunnelManager.start 호출 시 예외 없이 같은 숫자 포트 터널 반환",
            ok_e8a,
            f"p0={p0}, p1={p1}, err={err}, echo_ok={echo_ok}",
        )
    finally:
        tunnels.Tunnel._connect = orig_connect
        try:
            mgr.stop("e8a_tun")
        except Exception:
            pass


def main():
    srv_a, port_a, stop_a = start_tagged_echo_server(b"A")
    srv_b, port_b, stop_b = start_tagged_echo_server(b"B")
    try:
        test_e1(port_a, port_b)
        test_e2(port_a)
        test_e3(port_a, port_b)
        test_e4(port_a)
        test_e5()
        test_e8a(port_a)
    finally:
        stop_a.set()
        stop_b.set()
        for s in (srv_a, srv_b):
            try:
                s.close()
            except Exception:
                pass

    print(f"\n{sum(results)}/{len(results)} 통과")
    os._exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
