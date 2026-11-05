"""dev/harness/t_sec2.py
보안 수정 2차 (2026-11-04) T1~T4 명세 검증 시험.
구현 코드를 참조하지 않고 SPEC.md 및 INTERFACE.md 명세만으로 작성됨.

검증 항목:
- T1 (a): --no-token 없이 루프백 실행 시 토큰 없는 WebSocket 접속 거부, 올바른 토큰은 접속 허용
- T1 (b): DATA/token 파일 생성 및 /api shutdown 정상 종료 후 토큰 파일 자동 삭제 확인
- T1 (c): --no-token + --host 0.0.0.0 실행 시 시작 거부(0 아닌 종료코드)
- T1 (d): --no-token 루프백 실행 시 토큰 없이 WebSocket 접속 허용
- T1 (e): 서버 콘솔 출력 및 data/server.log 에 토큰 원문 노출 없음
- T2: proxy_socket 에 host/port 잘못된 값 전달 시 ValueError 및 소켓 미생성(호출 0회),
      IPv6 '::1' 대상 CONNECT 요청 줄에 '[::1]:22' 포맷 확인
- T3: _rdp_file 에 host·username 에 '\r\n' 주입 시 ValueError 및 .rdp 파일 미생성 (재귀 탐색)
- T4: _make_shortcut 의 sid 정규식 위반('a b', 'x"&calc', 65자 등) 시 ValueError

실행:
    python -u dev/harness/t_sec2.py
종료 코드: 하나라도 실패 시 1, 모두 성공 시 0
"""
import os
import sys
import time
import json
import socket
import tempfile
import shutil
import threading
import subprocess
from pathlib import Path

# 프로젝트 루트 경로 추가
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT_DIR)

from wst import sshconn
from wst import api
from wst import common

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    status = "PASS" if ok else "FAIL"
    msg = f"{status} {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def wait_port_open(host, port, timeout=5.0):
    """지정 포트가 열릴 때까지 대기"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def make_ws_upgrade_request(host, port, path, origin=None):
    """CSWSH 방지를 통과하기 위해 Host와 일치하는 Origin 헤더를 기본 포함하는 WS 업그레이드 요청 생성"""
    if origin is None:
        origin = f"http://{host}:{port}"
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"Origin: {origin}\r\n"
        f"\r\n"
    )


def raw_ws_handshake(host, port, path, origin=None):
    """
    외부 websockets 패키지 버전 차이에 의존하지 않고
    표준 소켓으로 HTTP WebSocket Upgrade 핸드셰이크를 보내 상태 코드를 반환.
    반환값: (status_code: int, full_response: str)
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    try:
        s.connect((host, port))
        req = make_ws_upgrade_request(host, port, path, origin)
        s.sendall(req.encode("utf-8"))
        resp = s.recv(4096).decode("latin-1", errors="replace")
        if not resp:
            return 0, ""
        first_line = resp.split("\r\n")[0]
        parts = first_line.split(" ")
        status_code = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
        return status_code, resp
    except Exception as e:
        return 0, str(e)
    finally:
        try:
            s.close()
        except OSError:
            pass


def open_ws_connection(host, port, path, origin=None):
    """
    WebSocket 연결을 수립하고 (socket, status_code)를 반환.
    호출자가 사용 후 socket을 닫아야 함.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect((host, port))
    req = make_ws_upgrade_request(host, port, path, origin)
    s.sendall(req.encode("utf-8"))
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(1024)
        if not chunk:
            break
        buf += chunk
    header_str = buf.decode("latin-1", errors="replace")
    first_line = header_str.split("\r\n")[0]
    parts = first_line.split(" ")
    code = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
    return s, code


def send_ws_text(sock, text):
    """
    RFC 6455 규격에 맞춰 클라이언트 마스킹 텍스트 프레임을 전송.
    """
    payload = text.encode("utf-8")
    length = len(payload)
    mask_key = b"\x12\x34\x56\x78"
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    if length < 126:
        header = bytearray([0x81, 0x80 | length])
    elif length < 65536:
        header = bytearray([0x81, 0x80 | 126, (length >> 8) & 0xFF, length & 0xFF])
    else:
        raise ValueError("Payload too large for test helper")
    sock.sendall(header + mask_key + masked)


# ─────────────────────────────────────────────────────────────
# T1: 로컬 모드 접속 토큰 검증
# ─────────────────────────────────────────────────────────────
def test_t1():
    print("[T1] 로컬 모드 접속 토큰 검증 시작")

    # (a), (b), (e): 기본 루프백 실행 (토큰 자동 생성)
    tmp_data1 = tempfile.mkdtemp(prefix="wst_sec2_t1_default_")
    port1 = 18032
    env1 = os.environ.copy()
    env1["WEBSSH_DATA"] = tmp_data1
    env1["PYTHONIOENCODING"] = "utf-8"

    server_cmd1 = [
        sys.executable,
        os.path.join(ROOT_DIR, "server.py"),
        "--no-tls",
        "--port",
        str(port1),
        "--host",
        "127.0.0.1",
    ]

    proc1 = subprocess.Popen(
        server_cmd1,
        cwd=ROOT_DIR,
        env=env1,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    token = None
    token_path = Path(tmp_data1) / "token"
    try:
        ok_open = wait_port_open("127.0.0.1", port1, timeout=6.0)
        check("T1-start: 기본 루프백 서버 포트 바인딩", ok_open, f"port {port1}")

        # T1 (b) 생성: DATA/token 파일 생성 확인
        t0 = time.time()
        while time.time() - t0 < 3.0 and not token_path.exists():
            time.sleep(0.05)

        token_exists_before = token_path.exists()
        if token_exists_before:
            token = token_path.read_text(encoding="utf-8").strip()

        check(
            "T1 (b) 생성: DATA/token 파일 생성 및 길이",
            token_exists_before and bool(token) and len(token) >= 24,
            f"token len={len(token) if token else 0}",
        )

        # T1 (a): WebSocket 경로 검사
        # 토큰 없음: 올바른 Origin을 전송해도 토큰이 없으므로 거부되어야 함
        ws_path_no_token = "/ws"
        code_no_token, _ = raw_ws_handshake("127.0.0.1", port1, ws_path_no_token)
        check(
            "T1 (a) 거부: 토큰 없는 WebSocket 접속 거부",
            code_no_token != 101,
            f"HTTP status={code_no_token} (101이 아니어야 함)",
        )

        # 잘못된 토큰: 올바른 Origin을 전송해도 토큰 불일치로 거부되어야 함
        code_bad_token, _ = raw_ws_handshake("127.0.0.1", port1, "/ws?t=invalid_token_test")
        check(
            "T1 (a) 거부: 틀린 토큰 WebSocket 접속 거부",
            code_bad_token != 101,
            f"HTTP status={code_bad_token} (101이 아니어야 함)",
        )

        # 맞는 토큰 허용
        code_ok, _ = raw_ws_handshake("127.0.0.1", port1, f"/ws?t={token}")
        check(
            "T1 (a) 허용: 올바른 토큰 WebSocket 접속 허용",
            code_ok == 101,
            f"HTTP status={code_ok} (101 Switching Protocols 기대)",
        )

        # T1 (b) 정상 종료: /api WebSocket으로 shutdown 요청 전송
        normal_shutdown = False
        shutdown_sent = False
        try:
            ws_sock, ws_code = open_ws_connection("127.0.0.1", port1, f"/api?t={token}")
            if ws_code == 101:
                send_ws_text(ws_sock, json.dumps({"op": "shutdown", "id": 1}))
                shutdown_sent = True
            try:
                ws_sock.close()
            except OSError:
                pass
        except Exception as e:
            shutdown_sent = False

        # 최대 10초 프로세스 정상 종료 대기
        try:
            proc1.wait(timeout=10.0)
            normal_shutdown = True
        except subprocess.TimeoutExpired:
            normal_shutdown = False

        check(
            "T1 (b) 정상 종료: /api WebSocket shutdown 후 프로세스 정상 종료",
            normal_shutdown,
            f"shutdown_sent={shutdown_sent}, returncode={proc1.returncode}",
        )

        # 서버 정상 종료 후 DATA/token 파일 자동 삭제 확인
        token_deleted = not token_path.exists()
        check(
            "T1 (b) 삭제: 서버 정상 종료 후 DATA/token 파일 자동 삭제",
            token_deleted,
            f"token_exists={token_path.exists()}",
        )

    finally:
        # 정상 종료에 실패해 남아있을 경우 사후 강제 종료 정리
        if proc1.poll() is None:
            proc1.kill()
            try:
                proc1.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                pass

        out1, err1 = proc1.communicate()

        # T1 (e): 서버 출력 및 data/server.log 에 토큰 원문 노출 여부 확인
        log_file = Path(tmp_data1) / "server.log"
        log_txt = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
        combined_logs = (out1 or "") + "\n" + (err1 or "") + "\n" + log_txt

        token_leaked = bool(token) and (token in combined_logs)
        check(
            "T1 (e): 서버 출력 및 log 에 토큰 원문 미노출",
            not token_leaked,
            "토큰 원문이 콘솔 출력이나 log 파일에 포함되지 않음 (t=*** 마스킹 기대)",
        )

        shutil.rmtree(tmp_data1, ignore_errors=True)

    # (c): --no-token + --host 0.0.0.0 실행 시 시작 거부 (0 아닌 종료 코드)
    tmp_data_c = tempfile.mkdtemp(prefix="wst_sec2_t1_c_")
    env_c = os.environ.copy()
    env_c["WEBSSH_DATA"] = tmp_data_c
    env_c["PYTHONIOENCODING"] = "utf-8"
    cmd_c = [
        sys.executable,
        os.path.join(ROOT_DIR, "server.py"),
        "--no-tls",
        "--port",
        "18033",
        "--no-token",
        "--host",
        "0.0.0.0",
    ]
    res_c = subprocess.run(
        cmd_c,
        cwd=ROOT_DIR,
        env=env_c,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5.0,
    )
    check(
        "T1 (c): --no-token + --host 0.0.0.0 시작 거부",
        res_c.returncode != 0,
        f"exit code={res_c.returncode} (0이 아니어야 함)",
    )
    shutil.rmtree(tmp_data_c, ignore_errors=True)

    # (d): --no-token 루프백 → 토큰 없이 접속됨 (Origin 포함)
    tmp_data_d = tempfile.mkdtemp(prefix="wst_sec2_t1_d_")
    port_d = 18034
    env_d = os.environ.copy()
    env_d["WEBSSH_DATA"] = tmp_data_d
    env_d["PYTHONIOENCODING"] = "utf-8"
    cmd_d = [
        sys.executable,
        os.path.join(ROOT_DIR, "server.py"),
        "--no-tls",
        "--port",
        str(port_d),
        "--no-token",
        "--host",
        "127.0.0.1",
    ]
    proc_d = subprocess.Popen(
        cmd_d,
        cwd=ROOT_DIR,
        env=env_d,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        ok_open_d = wait_port_open("127.0.0.1", port_d, timeout=5.0)
        check("T1 (d)-start: --no-token 루프백 서버 기동", ok_open_d, f"port {port_d}")

        code_d, _ = raw_ws_handshake("127.0.0.1", port_d, "/ws")
        check(
            "T1 (d): --no-token 루프백 시 토큰 없이 접속 성공",
            code_d == 101,
            f"HTTP status={code_d} (101 기대)",
        )
    finally:
        # 정리: 정상 종료 시도 후 미종료 시 kill
        try:
            ws_sock_d, ws_code_d = open_ws_connection("127.0.0.1", port_d, "/api")
            if ws_code_d == 101:
                send_ws_text(ws_sock_d, json.dumps({"op": "shutdown", "id": 1}))
            try:
                ws_sock_d.close()
            except OSError:
                pass
            proc_d.wait(timeout=3.0)
        except Exception:
            pass

        if proc_d.poll() is None:
            proc_d.kill()
            try:
                proc_d.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                pass

        shutil.rmtree(tmp_data_d, ignore_errors=True)


# ─────────────────────────────────────────────────────────────
# T2: HTTP CONNECT 프록시 줄바꿈 주입 방지 (wst/sshconn.py)
# ─────────────────────────────────────────────────────────────
def test_t2():
    print("[T2] proxy_socket 입력 검증 및 IPv6 CONNECT 포맷 검증 시작")

    real_create_connection = socket.create_connection
    real_socket_cls = socket.socket
    socket_call_count = [0]

    def guarded_create_connection(*args, **kwargs):
        socket_call_count[0] += 1
        raise AssertionError("소켓 함수가 호출되면 안 됩니다 (검증 전 호출 차단 필수)")

    class GuardedSocket(real_socket_cls):
        def connect(self, *args, **kwargs):
            socket_call_count[0] += 1
            raise AssertionError("소켓 connect가 호출되면 안 됩니다 (검증 전 호출 차단 필수)")

    # 1. 대상 host / port 유효성 검사 (소켓 열기 전 ValueError 발생 확인)
    bad_hosts = ["a\r\nX: y", "a b", ""]
    # 숫자로만 된 문자열('80')은 허용되므로 거부 목록에서 제외; 주입/문자 혼합값 거부 검증
    bad_ports = [0, 70000, "80\r\n", "8a", " 80"]
    valid_proxy = {"type": "http", "host": "127.0.0.1", "port": 8080}

    # monkeypatch 적용
    socket.create_connection = guarded_create_connection
    socket.socket = GuardedSocket
    try:
        for bh in bad_hosts:
            raised = False
            socket_call_count[0] = 0
            try:
                sshconn.proxy_socket(valid_proxy, bh, 22)
            except ValueError:
                raised = True
            except Exception:
                raised = False
            check(
                f"T2 host 거부: {repr(bh)}",
                raised and socket_call_count[0] == 0,
                f"ValueError={raised}, socket calls={socket_call_count[0]}",
            )

        for bp in bad_ports:
            raised = False
            socket_call_count[0] = 0
            try:
                sshconn.proxy_socket(valid_proxy, "example.com", bp)
            except ValueError:
                raised = True
            except Exception:
                raised = False
            check(
                f"T2 port 거부: {repr(bp)}",
                raised and socket_call_count[0] == 0,
                f"ValueError={raised}, socket calls={socket_call_count[0]}",
            )

        # 프록시 자체의 host/port도 검사해야 함
        bad_proxies = [
            {"type": "http", "host": "proxy\r\nbad", "port": 8080},
            {"type": "http", "host": "127.0.0.1", "port": -1},
            {"type": "http", "host": "127.0.0.1", "port": 99999},
        ]
        for bp_cfg in bad_proxies:
            raised = False
            socket_call_count[0] = 0
            try:
                sshconn.proxy_socket(bp_cfg, "example.com", 22)
            except ValueError:
                raised = True
            except Exception:
                raised = False
            check(
                f"T2 proxy 자체 설정 거부: {repr(bp_cfg)}",
                raised and socket_call_count[0] == 0,
                f"ValueError={raised}, socket calls={socket_call_count[0]}",
            )
    finally:
        # monkeypatch 복구
        socket.create_connection = real_create_connection
        socket.socket = real_socket_cls

    # 2. IPv6 대상 '::1' CONNECT 줄 포맷 검증 ([::1]:22)
    fake_proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    fake_proxy.bind(("127.0.0.1", 0))
    fake_proxy.listen(1)
    proxy_port = fake_proxy.getsockname()[1]

    captured_req = []

    def proxy_worker():
        try:
            c, _ = fake_proxy.accept()
            data = c.recv(1024)
            captured_req.append(data)
            # 200 Established 응답 전송
            c.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            c.close()
        except Exception:
            pass

    th = threading.Thread(target=proxy_worker, daemon=True)
    th.start()

    try:
        sock_ret = sshconn.proxy_socket({"type": "http", "host": "127.0.0.1", "port": proxy_port}, "::1", 22)
        if sock_ret:
            try:
                sock_ret.close()
            except OSError:
                pass
    except Exception:
        pass
    finally:
        fake_proxy.close()
        th.join(timeout=1.0)

    raw_req = captured_req[0].decode("latin-1", errors="replace") if captured_req else ""
    first_line = raw_req.split("\r\n")[0] if raw_req else ""
    expected_line_prefix = "CONNECT [::1]:22 "
    check(
        "T2 IPv6 CONNECT 요청 줄 포맷",
        first_line.startswith(expected_line_prefix),
        f"수신된 요청 첫 줄: {repr(first_line)} (기대: {expected_line_prefix}HTTP/1.1)",
    )


# ─────────────────────────────────────────────────────────────
# T3: RDP 파일 설정 주입 방지 (wst/api.py)
# ─────────────────────────────────────────────────────────────
def test_t3():
    print("[T3] _rdp_file 줄바꿈 주입 방지 검증 시작")

    tmp_data = tempfile.mkdtemp(prefix="wst_sec2_t3_")
    orig_data = getattr(common, "DATA", None)
    common.DATA = Path(tmp_data)

    try:
        # host / username 에 \r\n 주입 시도
        bad_cases = [
            ({"host": "10.0.0.1\r\nfull address:s:evil.com", "username": "admin"}, "10.0.0.1:3389"),
            ({"host": "10.0.0.1\nfull address:s:evil.com", "username": "admin"}, "10.0.0.1:3389"),
            ({"host": "10.0.0.1", "username": "admin\r\nusername:s:evil"}, "10.0.0.1:3389"),
            ({"host": "10.0.0.1", "username": "admin"}, "10.0.0.1:3389\r\nscreen:i:1"),
        ]

        for s_dict, addr in bad_cases:
            raised = False
            files_before = set(Path(tmp_data).rglob("*.rdp"))
            try:
                api._rdp_file(s_dict, addr)
            except ValueError:
                raised = True
            except Exception:
                raised = False

            files_after = set(Path(tmp_data).rglob("*.rdp"))
            new_files = files_after - files_before

            check(
                f"T3 _rdp_file 주입 거부: host={repr(s_dict.get('host'))}, user={repr(s_dict.get('username'))}",
                raised and (len(new_files) == 0),
                f"ValueError={raised}, 신규 생성된 rdp 파일 수={len(new_files)}",
            )
    finally:
        if orig_data is not None:
            common.DATA = orig_data
        shutil.rmtree(tmp_data, ignore_errors=True)


# ─────────────────────────────────────────────────────────────
# T4: 바로가기 실행 인수 주입 방지 (wst/api.py)
# ─────────────────────────────────────────────────────────────
def test_t4():
    print("[T4] _make_shortcut sid 검증 시작")

    # sid 허용 정규식: ^[A-Za-z0-9_-]{1,64}$
    bad_sids = [
        "a b",
        'x"&calc',
        "a" * 65,
        "",
        "sid;calc.exe",
        "sid|notepad",
        "sid\r\n",
    ]

    for sid in bad_sids:
        raised = False
        try:
            api._make_shortcut("TestShortcut", sid)
        except ValueError:
            raised = True
        except Exception:
            raised = False

        check(
            f"T4 _make_shortcut 거부: sid={repr(sid)}",
            raised,
            f"ValueError 발생={raised}",
        )


def main():
    print("=== wst 보안 수정 2차 (T1~T4) 시험 시작 ===")
    test_t1()
    test_t2()
    test_t3()
    test_t4()

    pass_count = sum(1 for r in results if r)
    fail_count = len(results) - pass_count
    print(f"\n총 {len(results)}건 중 PASS: {pass_count}, FAIL: {fail_count}")

    if fail_count > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
