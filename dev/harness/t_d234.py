"""D2·D3·D4 시험:
- D2: 게이트웨이 RDP 다중 창 자격 증명 유지, 창 닫은 직후(10초 대기 중) 재실행 시 정리 경쟁 방지, 세션별 주소·자격 증명 분리
- D3: 게이트웨이 RDP 터널 연결 중 같은 세션 동시 호출 시 ':None' 주소 미발생
- D4: 터널 stop() 이후 어떤 경로(시작 실패, 재접속 실패, 재접속 성공)로도 상태가 'off' 이외로 덮이지 않음
실행: WEBSSH_DATA=<임시 폴더> python -u dev/harness/t_d234.py   (가짜 sshd 2222가 떠 있어야 함)"""
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


def start_echo_server():
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
                        conn.sendall(data)
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


def ping_addr(addr, timeout=5.0):
    host, port_s = addr.rsplit(":", 1)
    with socket.create_connection((host, int(port_s)), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(b"ping")
        return s.recv(10) == b"ping"


def parse_rdp_full_address(rdp_path):
    for enc in ("utf-16", "utf-8"):
        try:
            txt = open(rdp_path, encoding=enc).read()
            if "full address:s:" in txt:
                return txt.split("full address:s:", 1)[1].splitlines()[0].strip()
        except Exception:
            continue
    return ""


def test_d2_and_d3(eport):
    orig_popen = api.subprocess.Popen
    orig_ssh_params = api.ssh_params
    orig_write_cred = api.vault.write_rdp_cred
    orig_delete_cred = api.vault.delete_rdp_cred
    orig_vault = api.vault.VAULT
    orig_connect = tunnels.Tunnel._connect

    creds = []
    cred_lock = threading.Lock()
    spawned_procs = []

    def rec_write(h, u, p):
        with cred_lock:
            creds.append(("write", h, p))

    def rec_delete(h):
        with cred_lock:
            creds.append(("delete", h, None))

    class StubVault:
        def get(self, key):
            return {"password": "pw-" + key.split("@")[0]}

    class FakeMstsc:
        def __init__(self, args):
            self.args = args
            self.done = threading.Event()
            self.full_address = parse_rdp_full_address(args[1]) if len(args) > 1 else ""
            with cred_lock:
                spawned_procs.append(self)

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
    sA = {"id": "d2A", "name": "A", "host": "127.0.0.1", "port": eport, "gateway": "gw", "username": "ua"}
    sB = {"id": "d2B", "name": "B", "host": "127.0.0.1", "port": eport, "gateway": "gw", "username": "ub"}
    sC = {"id": "d3C", "name": "C", "host": "127.0.0.1", "port": eport, "gateway": "gw", "username": "uc"}

    try:
        # ── D2-3: 서로 다른 세션은 서로 다른 주소와 자격 증명 ──
        addrA1 = api._launch_rdp(sA, data, SEC, ask_yes)
        pA1 = spawned_procs[-1]
        addrB1 = api._launch_rdp(sB, data, SEC, ask_yes)
        pB1 = spawned_procs[-1]
        hA, hB = addrA1.rsplit(":", 1)[0], addrB1.rsplit(":", 1)[0]
        writes_ab = [(h, p) for op, h, p in creds if op == "write"]
        ok_d2_3 = (
            hA != hB
            and hA.startswith("127.77.")
            and hB.startswith("127.77.")
            and ping_addr(addrA1)
            and ping_addr(addrB1)
            and (hA, "pw-rdp:ua") in writes_ab
            and (hB, "pw-rdp:ub") in writes_ab
        )
        idx_b = len(creds)
        pB1.done.set()
        time.sleep(0.4)
        after_b = creds[idx_b:]
        ok_d2_3 = ok_d2_3 and ("delete", hB, None) in after_b and not any(op == "delete" and h == hA for op, h, _ in after_b)
        check("D2-3 서로 다른 세션은 서로 다른 주소·자격 증명 및 개별 정리", ok_d2_3, f"addrA={addrA1}, addrB={addrB1}, after_b={after_b}")

        # ── D2-1: 같은 세션 다중 창 열림 중 하나만 닫아도 자격 증명 유지, 마지막 창 닫힐 때 삭제 ──
        addrA2 = api._launch_rdp(sA, data, SEC, ask_yes)
        pA2 = spawned_procs[-1]
        idx_a1 = len(creds)
        pA1.done.set()
        time.sleep(0.5)
        after_a1_close = creds[idx_a1:]
        kept_while_open = not any(op == "delete" and h == hA for op, h, _ in after_a1_close)

        idx_a2 = len(creds)
        pA2.done.set()
        time.sleep(0.4)
        after_a2_close = creds[idx_a2:]
        deleted_on_last = any(op == "delete" and h == hA for op, h, _ in after_a2_close)
        check(
            "D2-1 한 세션의 창이 하나라도 열려 있는 동안 자격 증명 유지, 마지막 창 닫힐 때 삭제",
            addrA2 == addrA1 and kept_while_open and deleted_on_last,
            f"after_first_close={after_a1_close}, after_last_close={after_a2_close}",
        )

        # ── D2-2: 창을 닫은 직후(10초 정리 대기 중) 같은 세션을 다시 열면 새 실행의 자격 증명·터널이 유지됨 ──
        idx_reopen = len(creds)
        addrA3 = api._launch_rdp(sA, data, SEC, ask_yes)
        pA3 = spawned_procs[-1]
        hA3 = addrA3.rsplit(":", 1)[0]
        # 새 창 pA3은 TCP 연결을 맺지 않은 채(conns == 0) 11초 동안 열려 있음
        time.sleep(11.0)
        events_since_reopen = [(op, h) for op, h, _ in creds[idx_reopen:] if h == hA3]
        # 마지막 동작이 write여야 하며(중간이나 10초 뒤에 delete가 불리면 안 됨), 터널이 살아 있어야 함
        cred_still_valid = bool(events_since_reopen) and events_since_reopen[-1][0] == "write" and (
            "delete",
            hA3,
        ) not in events_since_reopen[1:]
        tun_a = api.manager.tunnels.get("rdp-" + sA["id"])
        tun_still_on = tun_a is not None and tun_a.state == "on"
        ping_ok = False
        if tun_still_on:
            try:
                ping_ok = ping_addr(addrA3)
            except Exception:
                ping_ok = False
        check(
            "D2-2 창 닫은 직후(10초 정리 대기 중) 재실행 시 새 창의 자격 증명·터널 유지",
            cred_still_valid and tun_still_on and ping_ok,
            f"events={events_since_reopen}, state={getattr(tun_a, 'state', None)}, ping={ping_ok}",
        )
        pA3.done.set()
        time.sleep(0.3)

        # ── D3: 터널이 연결 중일 때 같은 세션을 동시에 또 열어도 ':None' 주소가 나오지 않음 ──
        def slow_connect(self):
            time.sleep(1.5)
            return orig_connect(self)

        tunnels.Tunnel._connect = slow_connect
        d3_Index = len(spawned_procs)
        d3_out = [None, None]
        d3_err = [None, None]

        def call_launch(i):
            try:
                d3_out[i] = api._launch_rdp(sC, data, SEC, ask_yes)
            except Exception as e:
                d3_err[i] = e

        th1 = threading.Thread(target=call_launch, args=(0,), daemon=True)
        th2 = threading.Thread(target=call_launch, args=(1,), daemon=True)
        th1.start()
        time.sleep(0.25)
        th2.start()
        th1.join(timeout=10.0)
        th2.join(timeout=10.0)

        d3_procs = spawned_procs[d3_Index:]
        d3_addrs = [p.full_address for p in d3_procs]

        def valid_addr(a):
            if not isinstance(a, str) or ":" not in a or "None" in a:
                return False
            h, p = a.rsplit(":", 1)
            return h.startswith("127.77.") and p.isdigit() and int(p) > 0

        first_ok = d3_err[0] is None and valid_addr(d3_out[0])
        second_ok = (d3_err[1] is None and d3_out[1] == d3_out[0] and valid_addr(d3_out[1])) or (
            d3_err[1] is not None and d3_out[1] is None
        )
        mstsc_ok = len(d3_addrs) >= 1 and all(valid_addr(a) for a in d3_addrs)
        check(
            "D3 게이트웨이 터널 연결 중 동시 _launch_rdp 호출 시 숫자 포트 반환 및 ':None' 미발생",
            first_ok and second_ok and mstsc_ok,
            f"out={d3_out}, err={d3_err}, mstsc_addrs={d3_addrs}",
        )
    finally:
        tunnels.Tunnel._connect = orig_connect
        for p in spawned_procs:
            p.done.set()
        for sid in ("d2A", "d2B", "d3C"):
            try:
                api.manager.stop("rdp-" + sid)
            except Exception:
                pass
        api.subprocess.Popen = orig_popen
        api.ssh_params = orig_ssh_params
        api.vault.write_rdp_cred = orig_write_cred
        api.vault.delete_rdp_cred = orig_delete_cred
        api.vault.VAULT = orig_vault


def test_d4(eport):
    orig_connect = tunnels.Tunnel._connect
    cfg = {"type": "local", "listenPort": 0, "destHost": "127.0.0.1", "destPort": eport}
    params = {"host": "127.0.0.1", "port": 2222, "username": "test", "password": "pw"}

    # ── D4-a: 처음 시작 중(_connect 진행 중) stop() 호출 → 그 접속이 실패(예외) ──
    mgr_a = tunnels.TunnelManager()
    states_a = []
    t_holder_a = {}
    entered_a = threading.Event()
    release_a = threading.Event()

    def record_a(*args):
        t = t_holder_a.get("t") or mgr_a.tunnels.get("d4a")
        if t is not None:
            states_a.append(t.state)

    mgr_a.listeners.append(record_a)

    def connect_a(self):
        t_holder_a["t"] = self
        entered_a.set()
        release_a.wait(5.0)
        raise RuntimeError("connect failed after stop")

    tunnels.Tunnel._connect = connect_a
    try:
        th_start = threading.Thread(target=lambda: _ignore_exc(lambda: mgr_a.start("d4a", cfg, params, ask_yes)), daemon=True)
        th_start.start()
        assert entered_a.wait(5.0), "D4-a _connect 진입 실패"
        th_stop = threading.Thread(target=lambda: mgr_a.stop("d4a"), daemon=True)
        th_stop.start()
        time.sleep(0.15)
        release_a.set()
        th_stop.join(timeout=5.0)
        th_start.join(timeout=5.0)
        time.sleep(0.3)

        t_a = t_holder_a.get("t") or mgr_a.tunnels.get("d4a")
        after_off_a = states_a[states_a.index("off") + 1 :] if "off" in states_a else ["missing_off"]
        ok_a = t_a is not None and t_a.state == "off" and all(s == "off" for s in after_off_a)
        check(
            "D4-a 시작(_connect) 중 stop() 후 접속 실패 시 상태 off 유지",
            ok_a,
            f"final={getattr(t_a, 'state', None)}, states={states_a}",
        )
    finally:
        tunnels.Tunnel._connect = orig_connect
        try:
            mgr_a.stop("d4a")
        except Exception:
            pass

    # ── D4-b: 연결 끊김 후 재접속 시도(_connect) 중 stop() 호출 → 재접속 실패 ──
    mgr_b = tunnels.TunnelManager()
    states_b = []
    t_holder_b = {}
    entered_b = threading.Event()
    release_b = threading.Event()

    def record_b(*args):
        t = t_holder_b.get("t") or mgr_b.tunnels.get("d4b")
        if t is not None:
            states_b.append(t.state)

    mgr_b.listeners.append(record_b)
    try:
        mgr_b.start("d4b", cfg, params, ask_yes)
        t_b = mgr_b.tunnels["d4b"]
        t_holder_b["t"] = t_b

        def reconnect_fail(self):
            entered_b.set()
            release_b.wait(5.0)
            raise RuntimeError("reconnect failed after stop")

        tunnels.Tunnel._connect = reconnect_fail
        _drop_tunnel_ssh(t_b)
        entered = entered_b.wait(8.0)
        th_stop = threading.Thread(target=lambda: mgr_b.stop("d4b"), daemon=True)
        th_stop.start()
        time.sleep(0.15)
        release_b.set()
        th_stop.join(timeout=5.0)
        time.sleep(0.5)

        off_indices = [i for i, s in enumerate(states_b) if s == "off"]
        after_off_b = states_b[off_indices[0] + 1 :] if off_indices else ["missing_off"]
        ok_b = entered and t_b.state == "off" and all(s == "off" for s in after_off_b)
        check(
            "D4-b 재접속(_connect) 중 stop() 후 재접속 실패 시 상태 off 유지",
            ok_b,
            f"entered={entered}, final={t_b.state}, states={states_b}",
        )
    finally:
        tunnels.Tunnel._connect = orig_connect
        try:
            mgr_b.stop("d4b")
        except Exception:
            pass

    # ── D4-c: 연결 끊김 후 재접속 시도(_connect) 중 stop() 호출 → 재접속 성공 ──
    mgr_c = tunnels.TunnelManager()
    states_c = []
    t_holder_c = {}
    entered_c = threading.Event()
    release_c = threading.Event()

    def record_c(*args):
        t = t_holder_c.get("t") or mgr_c.tunnels.get("d4c")
        if t is not None:
            states_c.append(t.state)

    mgr_c.listeners.append(record_c)
    try:
        mgr_c.start("d4c", cfg, params, ask_yes)
        t_c = mgr_c.tunnels["d4c"]
        t_holder_c["t"] = t_c

        def reconnect_succeed(self):
            entered_c.set()
            release_c.wait(5.0)
            return orig_connect(self)

        tunnels.Tunnel._connect = reconnect_succeed
        _drop_tunnel_ssh(t_c)
        entered = entered_c.wait(8.0)
        th_stop = threading.Thread(target=lambda: mgr_c.stop("d4c"), daemon=True)
        th_stop.start()
        time.sleep(0.15)
        release_c.set()
        th_stop.join(timeout=5.0)
        time.sleep(0.5)

        off_indices = [i for i, s in enumerate(states_c) if s == "off"]
        after_off_c = states_c[off_indices[0] + 1 :] if off_indices else ["missing_off"]
        ok_c = entered and t_c.state == "off" and all(s == "off" for s in after_off_c)
        check(
            "D4-c 재접속(_connect) 중 stop() 후 재접속 성공 시 상태 off 유지",
            ok_c,
            f"entered={entered}, final={t_c.state}, states={states_c}",
        )
    finally:
        tunnels.Tunnel._connect = orig_connect
        try:
            mgr_c.stop("d4c")
        except Exception:
            pass


def _ignore_exc(fn):
    try:
        fn()
    except Exception:
        pass


def _drop_tunnel_ssh(t):
    cl = getattr(t, "client", None)
    if cl is not None:
        try:
            tr = cl.get_transport()
            if tr is not None:
                tr.close()
        except Exception:
            pass
        try:
            cl.close()
        except Exception:
            pass


def main():
    echo_srv, eport, echo_stop = start_echo_server()
    try:
        test_d2_and_d3(eport)
        test_d4(eport)
    finally:
        echo_stop.set()
        try:
            echo_srv.close()
        except Exception:
            pass

    print(f"\n{sum(results)}/{len(results)} 통과")
    os._exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
