"""S1~S4 보안 명세 기반 검증 시험 (dev/harness/t_sec_h.py)
- S1: term._parse_mon 반환 load 검증 및 HTML/비정상 loadavg 주입 시 None 처리
- S2: 원격 모드 직접 SSH 루프백 접속 차단 (PermissionError, 소켓 시도 0회), jump hop(sock 인자) 및 로컬 모드 허용
- S3: DNS TOCTOU 방지 (check_remote_target 검증 IP 반환, 연결 시 해당 IP 사용, 루프백 차단, 로컬 모드 원형 반환)
- S4: FTPS 기본 인증서 검증(CERT_REQUIRED, check_hostname=True) 및 ftpInsecure=True 시 무검증
"""
import math
import os
import socket
import ssl
import sys
import ftplib

# 저장소 루트를 sys.path에 추가
HERE = os.path.dirname(os.path.abspath(__file__))
for candidate in (os.path.join(HERE, "..", ".."), HERE, os.getcwd()):
    cand_abs = os.path.abspath(candidate)
    if os.path.isdir(os.path.join(cand_abs, "wst")) and cand_abs not in sys.path:
        sys.path.insert(0, cand_abs)

from wst import common, term, sshconn, ftpconn

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def ask_yes(*_):
    return True


# ── S1: term._parse_mon 부하(load) 및 XSS 방지 검증 ──
def make_proc_out(load_str="0.15 0.25 0.35 1/150 12345"):
    sec1 = "cpu  100 20 30 400 10 5 2 0 0 0\n"
    sec2 = "MemTotal:       16384000 kB\nMemAvailable:    8192000 kB\n"
    sec3 = "/dev/root  102400000 51200000 51200000  50% /\n"
    sec4 = (
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        "  eth0: 10000000      1000    0    0    0     0          0         0  20000000      2000    0    0    0     0       0          0\n"
    )
    sec5 = f"{load_str}\n"
    sec6 = "123456.78 234567.89\n"
    return "@@\n".join([sec1, sec2, sec3, sec4, sec5, sec6])


def test_s1():
    # 1. 정상 /proc 형식: load가 float 3개 리스트인지 확인
    normal_out = make_proc_out("0.15 0.25 0.35 1/150 12345")
    try:
        res_normal = term._parse_mon(normal_out, None)
        if isinstance(res_normal, tuple):   # Claude 보정: _parse_mon은 (결과, 상태) 튜플 반환 (명세 표기 오류)
            res_normal = res_normal[0]
        load_val = res_normal.get("load") if isinstance(res_normal, dict) else None
        ok_normal = (
            isinstance(load_val, list)
            and len(load_val) == 3
            and all(isinstance(x, float) and math.isfinite(x) for x in load_val)
            and [round(x, 2) for x in load_val] == [0.15, 0.25, 0.35]
        )
        check("S1-1 정상 /proc 출력 파싱 시 load가 유한한 float 3개 리스트", ok_normal, f"load={load_val}")
    except Exception as e:
        check("S1-1 정상 /proc 출력 파싱 시 load가 유한한 float 3개 리스트", False, repr(e))

    # 2. loadavg에 HTML 문자열 포함 시: 예외 없이 load가 None인지 확인
    html_load_str = '<img src=x onerror="window.__xss=1"> 0 0 1/150 12345'
    html_out = make_proc_out(html_load_str)
    try:
        res_html = term._parse_mon(html_out, None)
        if isinstance(res_html, tuple):   # Claude 보정: _parse_mon은 (결과, 상태) 튜플 반환 (명세 표기 오류)
            res_html = res_html[0]
        load_html_val = res_html.get("load") if isinstance(res_html, dict) else -1
        ok_html = isinstance(res_html, dict) and (load_html_val is None)
        check("S1-2 loadavg에 HTML 문자열 주입 시 예외 없이 load가 None 반환", ok_html, f"load={load_html_val}")
    except Exception as e:
        check("S1-2 loadavg에 HTML 문자열 주입 시 예외 없이 load가 None 반환", False, repr(e))

    # 3. loadavg에 nan/inf 포함 시: load가 None인지 확인
    nan_out = make_proc_out("nan 0.25 0.35 1/150 12345")
    try:
        res_nan = term._parse_mon(nan_out, None)
        if isinstance(res_nan, tuple):   # Claude 보정: _parse_mon은 (결과, 상태) 튜플 반환 (명세 표기 오류)
            res_nan = res_nan[0]
        load_nan_val = res_nan.get("load") if isinstance(res_nan, dict) else -1
        ok_nan = isinstance(res_nan, dict) and (load_nan_val is None)
        check("S1-3 loadavg에 nan/inf 포함 시 load가 None 반환", ok_nan, f"load={load_nan_val}")
    except Exception as e:
        check("S1-3 loadavg에 nan/inf 포함 시 load가 None 반환", False, repr(e))


# ── S2: sshconn.connect_one 원격 루프백 직접 접속 차단 검증 ──
def test_s2():
    orig_local_mode = common.LOCAL_MODE
    orig_create_conn = socket.create_connection
    orig_sock_connect = socket.socket.connect

    conn_attempts = []

    def fake_create_connection(address, *args, **kwargs):
        conn_attempts.append(address)
        raise ConnectionRefusedError("mock connect refused")

    def fake_socket_connect(self, address):
        conn_attempts.append(address)
        raise ConnectionRefusedError("mock connect refused")

    socket.create_connection = fake_create_connection
    socket.socket.connect = fake_socket_connect

    try:
        # 1. LOCAL_MODE=False, 직접 연결(sock=None) 루프백 접속 시 PermissionError 및 소켓 시도 0회
        common.LOCAL_MODE = False
        conn_attempts.clear()
        p = {"host": "127.0.0.1", "port": 2222, "username": "test", "password": "pw"}
        perm_error_raised = False
        try:
            sshconn.connect_one(p, ask_yes)
        except PermissionError:
            perm_error_raised = True
        except Exception:
            perm_error_raised = False

        ok_s2_direct = perm_error_raised and (len(conn_attempts) == 0)
        check(
            "S2-1 원격 모드에서 127.0.0.1 직접 SSH 시 소켓 시도 전 PermissionError 발생",
            ok_s2_direct,
            f"perm_error={perm_error_raised}, conn_attempts={conn_attempts}",
        )

        # 2. sock 인자를 준 경우 (점프 다음 홉): 루프백 검사로 인한 PermissionError가 나지 않아야 함
        dummy_sock = socket.socket()
        sock_perm_error = False
        try:
            sshconn.connect_one(p, ask_yes, sock=dummy_sock)
        except PermissionError:
            sock_perm_error = True
        except Exception:
            # 다른 예외(가짜 소켓 핸드셰이크 실패 등)는 허용
            sock_perm_error = False
        finally:
            try:
                dummy_sock.close()
            except Exception:
                pass

        ok_s2_jump = not sock_perm_error
        check(
            "S2-2 점프 다음 홉(sock 인자 제공) 시 루프백 검사 PermissionError 미발생",
            ok_s2_jump,
            f"sock_perm_error={sock_perm_error}",
        )

        # 3. LOCAL_MODE=True: 127.0.0.1 접속 시 PermissionError 미발생 (소켓 연결 시도는 무방)
        common.LOCAL_MODE = True
        local_perm_error = False
        try:
            sshconn.connect_one(p, ask_yes)
        except PermissionError:
            local_perm_error = True
        except Exception:
            local_perm_error = False

        ok_s2_local = not local_perm_error
        check(
            "S2-3 로컬 모드에서는 127.0.0.1 SSH 접속 시 PermissionError 미발생",
            ok_s2_local,
            f"local_perm_error={local_perm_error}",
        )

    finally:
        common.LOCAL_MODE = orig_local_mode
        socket.create_connection = orig_create_conn
        socket.socket.connect = orig_sock_connect


# ── S3: check_remote_target 및 DNS TOCTOU 방지 검증 ──
def test_s3():
    orig_local_mode = common.LOCAL_MODE
    orig_getaddrinfo = socket.getaddrinfo
    orig_create_conn = socket.create_connection
    orig_sock_connect = socket.socket.connect

    dns_calls = {}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        p = port if isinstance(port, int) else 0
        cnt = dns_calls.get(host, 0) + 1
        dns_calls[host] = cnt
        if host == "evil.example":
            ip = "203.0.113.10" if cnt == 1 else "127.0.0.1"
        elif host == "loopback.example":
            ip = "127.0.0.1"
        else:
            ip = "192.0.2.99"   # Claude 보정: 이 PC 주소 조회(gethostname)가 대상과 같은 IP를 받으면 '자기 PC'로 판정됨
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, p))]

    socket.getaddrinfo = fake_getaddrinfo

    try:
        # 1. LOCAL_MODE=False: check_remote_target이 검증된 공인 IP 반환
        common.LOCAL_MODE = False
        dns_calls.clear()
        res_ip = common.check_remote_target("evil.example")
        ok_s3_1 = res_ip == "203.0.113.10"
        check(
            "S3-1 check_remote_target('evil.example') 가 검증 통과한 IP 문자열 반환",
            ok_s3_1,
            f"res_ip={res_ip}, dns_calls={dns_calls.get('evil.example')}",
        )

        # 2. LOCAL_MODE=False: 루프백 IP로 해석되는 경우 PermissionError
        loopback_perm_error = False
        try:
            common.check_remote_target("loopback.example")
        except PermissionError:
            loopback_perm_error = True
        except Exception:
            loopback_perm_error = False

        check(
            "S3-2 check_remote_target이 루프백으로 풀리면 PermissionError 발생",
            loopback_perm_error,
            f"perm_error={loopback_perm_error}",
        )

        # 3. LOCAL_MODE=True: 검사 없이 host 그대로 반환
        common.LOCAL_MODE = True
        res_local = common.check_remote_target("loopback.example")
        ok_s3_3 = res_local == "loopback.example"
        check(
            "S3-3 로컬 모드에서는 check_remote_target이 host를 그대로 반환",
            ok_s3_3,
            f"res_local={res_local}",
        )

        # 4. DNS 재조회 TOCTOU 방지: connect_one 호출 시 검증된 IP(203.0.113.10)로 연결 시도
        common.LOCAL_MODE = False
        dns_calls.clear()
        conn_dests = []

        def rec_create_connection(address, *args, **kwargs):
            conn_dests.append(address)
            raise ConnectionRefusedError("mock connect")

        def rec_socket_connect(self, address):
            conn_dests.append(address)
            raise ConnectionRefusedError("mock connect")

        socket.create_connection = rec_create_connection
        socket.socket.connect = rec_socket_connect

        p_evil = {"host": "evil.example", "port": 2222, "username": "test", "password": "pw"}
        try:
            sshconn.connect_one(p_evil, ask_yes)
        except Exception:
            pass

        ok_s3_toctou = len(conn_dests) > 0 and all(dest[0] == "203.0.113.10" for dest in conn_dests)
        check(
            "S3-4 SSH 연결 시 검증 통과된 고정 IP('203.0.113.10')로 소켓 연결 시도 (TOCTOU 방지)",
            ok_s3_toctou,
            f"conn_dests={conn_dests}, dns_calls={dns_calls}",
        )

    finally:
        common.LOCAL_MODE = orig_local_mode
        socket.getaddrinfo = orig_getaddrinfo
        socket.create_connection = orig_create_conn
        socket.socket.connect = orig_sock_connect


# ── S4: ftpconn._login FTPS 인증서 검증 및 ftpInsecure 검증 ──
def test_s4():
    orig_ftp_tls = ftplib.FTP_TLS
    recorded_tls = []

    class FakeFTPTLS:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            ctx = kwargs.get("context")
            if ctx is None and len(args) >= 5:
                ctx = args[4]
            self.context = ctx
            recorded_tls.append(self)

        def connect(self, *args, **kwargs):
            return "220 Mock FTP"

        def login(self, *args, **kwargs):
            return "230 Logged in"

        def prot_p(self):
            pass

        def quit(self):
            pass

        def close(self):
            pass

    ftplib.FTP_TLS = FakeFTPTLS

    try:
        # 1. 기본 explicit TLS: ssl.CERT_REQUIRED 및 check_hostname=True 검증
        p_secure = {"host": "203.0.113.20", "port": 21, "tls": "explicit", "username": "u", "password": "p"}
        try:
            ftpconn._login(p_secure)
        except Exception:
            pass

        inst_secure = recorded_tls[-1] if recorded_tls else None
        ctx_secure = getattr(inst_secure, "context", None)
        ok_s4_secure = (
            ctx_secure is not None
            and getattr(ctx_secure, "verify_mode", None) == ssl.CERT_REQUIRED
            and getattr(ctx_secure, "check_hostname", False) is True
        )
        check(
            "S4-1 FTPS 기본 로그인 시 context verify_mode=CERT_REQUIRED 및 check_hostname=True",
            ok_s4_secure,
            f"ctx={ctx_secure}, verify_mode={getattr(ctx_secure, 'verify_mode', None)}, check_hostname={getattr(ctx_secure, 'check_hostname', None)}",
        )

        # 2. ftpInsecure=True 옵션 지정 시: CERT_NONE 및 check_hostname=False
        p_insecure = {
            "host": "203.0.113.20",
            "port": 21,
            "tls": "explicit",
            "username": "u",
            "password": "p",
            "ftpInsecure": True,
        }
        try:
            ftpconn._login(p_insecure)
        except Exception:
            pass

        inst_insecure = recorded_tls[-1] if len(recorded_tls) >= 2 else None
        ctx_insecure = getattr(inst_insecure, "context", None)
        ok_s4_insecure = (
            ctx_insecure is not None
            and getattr(ctx_insecure, "verify_mode", None) == ssl.CERT_NONE
            and getattr(ctx_insecure, "check_hostname", True) is False
        )
        check(
            "S4-2 ftpInsecure=True 지정 시 context verify_mode=CERT_NONE 및 check_hostname=False",
            ok_s4_insecure,
            f"ctx={ctx_insecure}, verify_mode={getattr(ctx_insecure, 'verify_mode', None)}, check_hostname={getattr(ctx_insecure, 'check_hostname', None)}",
        )

    finally:
        ftplib.FTP_TLS = orig_ftp_tls


def main():
    test_s1()
    test_s2()
    test_s3()
    test_s4()

    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} 통과")
    sys.exit(0 if (passed == total and total > 0) else 1)


if __name__ == "__main__":
    main()
