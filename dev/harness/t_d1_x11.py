"""D1 시험: X11 쿠키 확인 후 양방향 중계에 유휴 시간 제한(5초 타임아웃)이 없어야 함.
실행: WEBSSH_DATA=<임시 폴더> python -u dev/harness/t_d1_x11.py"""
import os
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import paramiko
from wst import x11


def check_port_available(port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            print(f"SKIP 127.0.0.1:{port} 포트가 이미 사용 중입니다.")
            os._exit(2)
    finally:
        probe.close()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", port))
        srv.listen(4)
        return srv
    except OSError as e:
        srv.close()
        print(f"SKIP 127.0.0.1:{port} 바인드 실패: {e}")
        os._exit(2)


def recv_exact(sock, n, timeout=12.0):
    sock.settimeout(timeout)
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError(f"연결 종료됨 ({len(buf)}/{n} 바이트 수신)")
        buf += chunk
    return buf


def make_setup(name, cookie):
    pad_n = (-len(name)) % 4
    pad_d = (-len(cookie)) % 4
    head = struct.pack("<cBHHHHH", b"l", 0, 11, 0, len(name), len(cookie), 0)
    return head + name + (b"\x00" * pad_n) + cookie + (b"\x00" * pad_d)


def read_setup(conn):
    head = recv_exact(conn, 12, timeout=5.0)
    n, d = struct.unpack("<HH", head[6:10])
    pad_n = (-n) % 4
    pad_d = (-d) % 4
    body = recv_exact(conn, n + pad_n + d + pad_d, timeout=5.0)
    name = body[:n]
    data = body[n + pad_n : n + pad_n + d]
    return name, data


class _X11ServerInterface(paramiko.ServerInterface):
    def __init__(self):
        self.x11_ready = threading.Event()
        self.shell_ready = threading.Event()
        self.cookie_hex = None

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_none(self, username):
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "password,none"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True

    def check_channel_x11_request(self, channel, single_connection, auth_protocol, auth_cookie, screen_number):
        self.cookie_hex = auth_cookie
        self.x11_ready.set()
        return True

    def check_channel_shell_request(self, channel):
        self.shell_ready.set()
        return True


def extract_fake_cookie(srv_if, client):
    raw = srv_if.cookie_hex
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="ignore")
    if isinstance(raw, str) and len(raw) == 32:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    c = getattr(client.get_transport(), "_webssh_x11_cookie", None)
    if isinstance(c, bytes):
        return c
    raise RuntimeError(f"x11-req 쿠키를 얻을 수 없음: {raw!r}")


results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def main():
    x_listener = check_port_available(x11.X_PORT)
    ssh_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ssh_listener.bind(("127.0.0.1", 0))
    ssh_listener.listen(2)
    ssh_port = ssh_listener.getsockname()[1]

    host_key = paramiko.RSAKey.generate(2048)
    srv_if = _X11ServerInterface()
    srv_holder = {}

    def accept_ssh():
        conn, _ = ssh_listener.accept()
        t = paramiko.Transport(conn)
        t.add_server_key(host_key)
        t.start_server(server=srv_if)
        srv_holder["transport"] = t
        srv_holder["conn"] = conn

    threading.Thread(target=accept_ssh, daemon=True).start()

    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    shell_ch = None
    try:
        cl.connect("127.0.0.1", ssh_port, username="test", password="pw", look_for_keys=False, allow_agent=False)
        shell_ch = x11.open_shell(cl, "xterm", 80, 24)
        assert srv_if.x11_ready.wait(5.0), "x11-req 미수신"
        assert srv_if.shell_ready.wait(5.0), "shell 요청 미수신"

        fake_cookie = extract_fake_cookie(srv_if, cl)
        real_cookie = x11.real_cookie()
        srv_t = srv_holder["transport"]

        # ── D1-1: X 서버가 setup 수신 후 7초간 무출력 뒤에 보낸 데이터를 원격(x11 채널)이 수신 ──
        x1_accepted = {}
        x1_done = threading.Event()

        def x_server_1():
            try:
                x_listener.settimeout(8.0)
                c, _ = x_listener.accept()
                x1_accepted["sock"] = c
                name, data = read_setup(c)
                x1_accepted["setup"] = (name, data)
                time.sleep(7.0)
                c.sendall(b"\x01\x00X_SERVER_AFTER_7S")
            except Exception as e:
                x1_accepted["err"] = e
            finally:
                x1_done.set()

        t1 = threading.Thread(target=x_server_1, daemon=True)
        t1.start()

        xch1 = srv_t.open_x11_channel(("127.0.0.1", 41001))
        try:
            xch1.sendall(make_setup(x11.AUTH_NAME, fake_cookie))
            payload1 = b"X_SERVER_AFTER_7S"
            want1 = b"\x01\x00" + payload1
            got1 = recv_exact(xch1, len(want1), timeout=11.0)
            x1_done.wait(3.0)
            setup_ok = x1_accepted.get("setup") == (x11.AUTH_NAME, real_cookie) and fake_cookie != real_cookie
            check(
                "D1-1 X 서버 → 원격: 7초 무출력 후 데이터 전달 및 쿠키 교체",
                got1 == want1 and setup_ok and "err" not in x1_accepted,
                f"recv={got1!r}, setup_ok={setup_ok}, err={x1_accepted.get('err')}",
            )
        except Exception as e:
            x1_done.wait(3.0)
            check("D1-1 X 서버 → 원격: 7초 무출력 후 데이터 전달 및 쿠키 교체", False, f"{type(e).__name__}: {e}")
        finally:
            try:
                xch1.close()
            except Exception:
                pass
            if "sock" in x1_accepted:
                try:
                    x1_accepted["sock"].close()
                except Exception:
                    pass

        # ── D1-2: 원격(x11 채널)이 7초간 무출력 뒤에 보낸 데이터를 X 서버가 수신하고 응답도 왕복 ──
        x2_accepted = {}
        x2_setup_evt = threading.Event()
        x2_done = threading.Event()
        payload2_r2x = b"REMOTE_AFTER_7S_IDLE"
        payload2_x2r = b"X_ACK_AFTER_7S_IDLE"

        def x_server_2():
            try:
                x_listener.settimeout(8.0)
                c, _ = x_listener.accept()
                x2_accepted["sock"] = c
                name, data = read_setup(c)
                x2_accepted["setup"] = (name, data)
                c.sendall(b"\x01")
                x2_setup_evt.set()
                got_r2x = recv_exact(c, len(payload2_r2x), timeout=11.0)
                x2_accepted["got"] = got_r2x
                c.sendall(payload2_x2r)
            except Exception as e:
                x2_accepted["err"] = e
                x2_setup_evt.set()
            finally:
                x2_done.set()

        t2 = threading.Thread(target=x_server_2, daemon=True)
        t2.start()

        xch2 = srv_t.open_x11_channel(("127.0.0.1", 41002))
        try:
            xch2.sendall(make_setup(x11.AUTH_NAME, fake_cookie))
            ack0 = recv_exact(xch2, 1, timeout=5.0)
            assert x2_setup_evt.wait(5.0), "X 서버 setup 미완료"
            time.sleep(7.0)
            xch2.sendall(payload2_r2x)
            got2_ack = recv_exact(xch2, len(payload2_x2r), timeout=5.0)
            x2_done.wait(3.0)
            ok2 = (
                ack0 == b"\x01"
                and x2_accepted.get("got") == payload2_r2x
                and got2_ack == payload2_x2r
                and "err" not in x2_accepted
            )
            check(
                "D1-2 원격 → X 서버: 7초 무출력 후 원격 데이터 전달 및 왕복 응답",
                ok2,
                f"x_got={x2_accepted.get('got')!r}, ack={got2_ack!r}, err={x2_accepted.get('err')}",
            )
        except Exception as e:
            x2_done.wait(3.0)
            check("D1-2 원격 → X 서버: 7초 무출력 후 원격 데이터 전달 및 왕복 응답", False, f"{type(e).__name__}: {e}")
        finally:
            try:
                xch2.close()
            except Exception:
                pass
            if "sock" in x2_accepted:
                try:
                    x2_accepted["sock"].close()
                except Exception:
                    pass
    finally:
        if shell_ch is not None:
            try:
                shell_ch.close()
            except Exception:
                pass
        try:
            cl.close()
        except Exception:
            pass
        if "transport" in srv_holder:
            try:
                srv_holder["transport"].close()
            except Exception:
                pass
        if "conn" in srv_holder:
            try:
                srv_holder["conn"].close()
            except Exception:
                pass
        try:
            ssh_listener.close()
        except Exception:
            pass
        try:
            x_listener.close()
        except Exception:
            pass

    print(f"\n{sum(results)}/{len(results)} 통과")
    os._exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
