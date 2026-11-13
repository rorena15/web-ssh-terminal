"""명세 B1 (2026-11-13) 검증 시험: 원격 모드·로컬 CA 제거 + 보안 소수정.
실행: WEBSSH_DATA=<임시 폴더> python dev/harness/t_b1.py"""
import ast
import datetime
import http.client
import inspect
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SERVER_PY = ROOT / "server.py"

if not os.environ.get("WEBSSH_DATA"):
    os.environ["WEBSSH_DATA"] = tempfile.mkdtemp(prefix="wst_b1_default_")

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import websockets.sync.client as ws_client

from wst import sftp, tls, tools

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_get(port: int, path: str, host_header: str | None) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("GET", path, skip_host=True)
        if host_header is not None:
            conn.putheader("Host", host_header)
        conn.endheaders()
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, body
    finally:
        conn.close()


def _wait_server_ready(port: int, proc: subprocess.Popen, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            status, _ = _http_get(port, "/", f"127.0.0.1:{port}")
            if status == 200:
                return True
        except OSError:
            pass
        time.sleep(0.15)
    return False


def _raw_ws_upgrade(port: int, path: str, host_header: str, origin: str | None = None) -> int:
    """127.0.0.1:port 로 직접 소켓 연결하여 Host/Origin 헤더를 지정한 HTTP Upgrade 상태 코드를 반환한다."""
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host_header}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==",
        "Sec-WebSocket-Version: 13",
    ]
    if origin is not None:
        lines.append(f"Origin: {origin}")
    req = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(req)
        data = b""
        while b"\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    first_line = data.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
    parts = first_line.split(" ")
    return int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0


# =====================================================================
# S1-1: --host 루프백 외 주소 거부 (종료 코드 2, "원격 모드" 출력)
# 결함 시: 0.0.0.0 또는 외부 IP 바인딩으로 서버가 기동되거나 종료 코드가 2가 아님 -> 실패
# =====================================================================
for bad_host in ("0.0.0.0", "10.0.0.5"):
    with tempfile.TemporaryDirectory(prefix="wst_b1_s1_1_") as tmpdir:
        env = os.environ.copy()
        env["WEBSSH_DATA"] = tmpdir
        env["PYTHONIOENCODING"] = "utf-8"
        port = _free_port()
        try:
            cp = subprocess.run(
                [sys.executable, str(SERVER_PY), "--host", bad_host, "--no-token", "--port", str(port)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                env=env,
            )
            out = (cp.stdout or "") + (cp.stderr or "")
            check(
                f"S1-1 --host {bad_host} 거부 (종료 코드 2 및 '원격 모드' 포함)",
                cp.returncode == 2 and "원격 모드" in out,
                f"rc={cp.returncode}, out={out.strip()[:120]!r}",
            )
        except Exception as e:
            check(f"S1-1 --host {bad_host} 거부 (종료 코드 2 및 '원격 모드' 포함)", False, repr(e))


# =====================================================================
# S1-3/7/8: HTTP 전용, Host 헤더 검증, /ca.crt 제거, WebSocket Origin/Host/토큰, --trust 호환
# =====================================================================
with tempfile.TemporaryDirectory(prefix="wst_b1_s1_srv_") as tmpdir:
    env = os.environ.copy()
    env["WEBSSH_DATA"] = tmpdir
    env["PYTHONIOENCODING"] = "utf-8"
    port = _free_port()
    other_port = _free_port()
    if other_port == port:
        other_port += 1
    token = "test_secret_token_b1"

    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PY), "--no-tls", "--token", token, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    try:
        ready = _wait_server_ready(port, proc, timeout=15.0)
        # HTTP GET / (Host 127.0.0.1:포트) -> 200
        if ready:
            st_root, _ = _http_get(port, "/", f"127.0.0.1:{port}")
            check("S1-3 HTTP GET / (Host 127.0.0.1:포트) -> 200", st_root == 200, f"status={st_root}")
        else:
            out = proc.stdout.read() if proc.stdout and proc.poll() is not None else "timeout"
            check("S1-3 HTTP GET / (Host 127.0.0.1:포트) -> 200", False, f"서버 미기동: {out[:160]!r}")

        # HTTPS 연결은 실패해야 함 (결함 시: TLS로 기동되어 핸드셰이크 성공)
        https_failed = False
        try:
            ctx = ssl._create_unverified_context()
            with socket.create_connection(("127.0.0.1", port), timeout=3) as raw_sock:
                with ctx.wrap_socket(raw_sock, server_hostname="127.0.0.1") as ssl_sock:
                    ssl_sock.sendall(f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
                    resp_bytes = ssl_sock.recv(1024)
                    if not resp_bytes.startswith(b"HTTP/"):
                        https_failed = True
        except (ssl.SSLError, OSError):
            https_failed = True
        check("S1-3 HTTPS 연결 실패 확인", ready and https_failed)

        # S1-7: 허용 Host 헤더 (localhost:포트, [::1]:포트 -> 200)
        for good_host in (f"localhost:{port}", f"[::1]:{port}"):
            try:
                st, _ = _http_get(port, "/", good_host)
                check(f"S1-7 허용 Host ({good_host}) -> 200", st == 200, f"status={st}")
            except Exception as e:
                check(f"S1-7 허용 Host ({good_host}) -> 200", False, repr(e))

        # S1-7: 비허용 Host 헤더 (evil.example:포트, 127.0.0.1:다른포트 -> 421)
        # 결함 시: Host 검사가 없어 200을 반환함
        for label, bad_host in (
            ("evil.example:포트", f"evil.example:{port}"),
            ("127.0.0.1:다른포트", f"127.0.0.1:{other_port}"),
        ):
            try:
                st, _ = _http_get(port, "/", bad_host)
                check(f"S1-7 비허용 Host ({label}) -> 421", st == 421, f"status={st}")
            except Exception as e:
                check(f"S1-7 비허용 Host ({label}) -> 421", False, repr(e))

        # S1-4: GET /ca.crt -> 404 (결함 시: 200으로 인증서 반환)
        try:
            st_ca, _ = _http_get(port, "/ca.crt", f"127.0.0.1:{port}")
            check("S1-4 GET /ca.crt -> 404", st_ca == 404, f"status={st_ca}")
        except Exception as e:
            check("S1-4 GET /ca.crt -> 404", False, repr(e))

        # S1-8: WebSocket /api 연결 시험
        # 1) 정상 Origin (http://127.0.0.1:포트) + 유효 토큰 -> 연결 성공
        try:
            with ws_client.connect(
                f"ws://127.0.0.1:{port}/api?t={token}",
                origin=f"http://127.0.0.1:{port}",
                open_timeout=5,
                close_timeout=2,
            ) as ws:
                check("S1-8 WebSocket 정상 Origin(http) + 토큰 -> 연결 성공", True)
        except Exception as e:
            check("S1-8 WebSocket 정상 Origin(http) + 토큰 -> 연결 성공", False, repr(e))

        # 2) Origin https://127.0.0.1:포트 -> 거부 (결함 시: https Origin도 허용됨)
        https_origin_rejected = False
        detail_https_origin = ""
        try:
            with ws_client.connect(
                f"ws://127.0.0.1:{port}/api?t={token}",
                origin=f"https://127.0.0.1:{port}",
                open_timeout=5,
                close_timeout=2,
            ) as ws:
                detail_https_origin = "연결 허용됨"
        except Exception as e:
            https_origin_rejected = True
            detail_https_origin = type(e).__name__
        check("S1-8 WebSocket https Origin -> 거부", ready and https_origin_rejected, detail_https_origin)

        # 3) Host 변조(evil.example:포트) + 같은 Origin(http://127.0.0.1:포트) -> 거부 (421 등 비-101)
        # 가정: websockets 클라이언트는 URI에서 Host 헤더를 자동 생성하므로 raw socket으로 HTTP Upgrade 요청을 보내 검증함
        try:
            ws_bad_host_st = _raw_ws_upgrade(
                port,
                f"/api?t={token}",
                host_header=f"evil.example:{port}",
                origin=f"http://127.0.0.1:{port}",
            )
            check(
                "S1-8 WebSocket Host 변조(evil.example:포트) -> 거부",
                ws_bad_host_st == 421 or (ws_bad_host_st != 101 and ws_bad_host_st >= 400),
                f"status={ws_bad_host_st}",
            )
        except Exception as e:
            check("S1-8 WebSocket Host 변조(evil.example:포트) -> 거부", False, repr(e))

        # 4) 토큰 없음 -> 거부
        # 가정: 서버가 핸드셰이크 단계(HTTP 4xx)에서 거부하거나, 연결 직후 즉시 프레임을 닫는(ConnectionClosed) 두 방식 모두 거부로 인정
        no_token_rejected = False
        detail_no_token = ""
        try:
            with ws_client.connect(
                f"ws://127.0.0.1:{port}/api",
                origin=f"http://127.0.0.1:{port}",
                open_timeout=5,
                close_timeout=2,
            ) as ws:
                try:
                    msg = ws.recv(timeout=2.0)
                    detail_no_token = f"연결 유지됨(수신: {msg!r})"
                except Exception as close_exc:
                    no_token_rejected = True
                    detail_no_token = f"핸드셰이크 후 즉시 종료({type(close_exc).__name__})"
        except Exception as e:
            no_token_rejected = True
            detail_no_token = f"핸드셰이크 거부({type(e).__name__})"
        check("S1-8 WebSocket 토큰 없음 -> 거부", ready and no_token_rejected, detail_no_token)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

# S1-3: --trust 인수를 함께 줘도 서버가 정상 기동 (별도 실행 1회)
with tempfile.TemporaryDirectory(prefix="wst_b1_s1_trust_") as tmpdir:
    env = os.environ.copy()
    env["WEBSSH_DATA"] = tmpdir
    env["PYTHONIOENCODING"] = "utf-8"
    port_trust = _free_port()
    proc_trust = subprocess.Popen(
        [sys.executable, str(SERVER_PY), "--no-tls", "--trust", "--token", "tok_trust", "--port", str(port_trust)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    try:
        ok_trust = _wait_server_ready(port_trust, proc_trust, timeout=15.0)
        check("S1-3 --trust 인수 포함 시 정상 기동", ok_trust)
    finally:
        proc_trust.terminate()
        try:
            proc_trust.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc_trust.kill()


# =====================================================================
# S2: wst.tls 단위 시험 (monkeypatch CERTS, CA_CRT, CA_KEY, SRV_CRT, SRV_KEY)
# =====================================================================
def _make_self_signed_ca() -> tuple[bytes, bytes, int]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WST Legacy Test CA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem_bytes = cert.public_bytes(serialization.Encoding.PEM)
    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    return pem_bytes, der_bytes, cert.serial_number


with tempfile.TemporaryDirectory(prefix="wst_b1_s2_") as tmpdir:
    certs_dir = Path(tmpdir) / "certs"
    ca_crt = certs_dir / "ca.crt"
    ca_key = certs_dir / "ca.key"
    srv_crt = certs_dir / "server.crt"
    srv_key = certs_dir / "server.key"
    four_files = (ca_crt, ca_key, srv_crt, srv_key)

    orig_attrs = {
        k: getattr(tls, k)
        for k in ("CERTS", "CA_CRT", "CA_KEY", "SRV_CRT", "SRV_KEY")
        if hasattr(tls, k)
    }
    orig_enum_certs = getattr(ssl, "enum_certificates", None)

    try:
        tls.CERTS = certs_dir
        tls.CA_CRT = ca_crt
        tls.CA_KEY = ca_key
        tls.SRV_CRT = srv_crt
        tls.SRV_KEY = srv_key

        # 1) 파일 없음 -> legacy_present() False
        check("S2-1 인증서 파일 없음 -> legacy_present() False", tls.legacy_present() is False)

        # 2) 자체 서명 CA 및 키 파일 생성 -> legacy_present() True
        pem_bytes, der_bytes, serial_num = _make_self_signed_ca()
        expected_serial_hex = format(serial_num, "x")

        def _write_four_files():
            certs_dir.mkdir(parents=True, exist_ok=True)
            ca_crt.write_bytes(pem_bytes)
            ca_key.write_text("dummy-ca-key", encoding="utf-8")
            srv_crt.write_text("dummy-srv-crt", encoding="utf-8")
            srv_key.write_text("dummy-srv-key", encoding="utf-8")

        _write_four_files()
        check("S2-1 인증서·키 파일 생성 후 -> legacy_present() True", tls.legacy_present() is True)

        # 3) "저장소에 없음" -> remove_legacy 호출 시 certutil 미실행, 4개 파일 및 폴더 삭제, untrusted True
        ssl.enum_certificates = lambda store_name: []
        run_calls_case3 = []

        def _fake_run_case3(args, **kwargs):
            run_calls_case3.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, "", "")

        res3 = tls.remove_legacy(run=_fake_run_case3)
        files_gone_3 = not any(p.exists() for p in four_files)
        dir_gone_3 = not certs_dir.exists()
        check(
            "S2-3 저장소에 없음 -> certutil 미실행, 4개 파일·폴더 삭제, untrusted True",
            len(run_calls_case3) == 0
            and files_gone_3
            and dir_gone_3
            and isinstance(res3, dict)
            and res3.get("untrusted") is True
            and not res3.get("error"),
            f"calls={len(run_calls_case3)}, files_gone={files_gone_3}, dir_gone={dir_gone_3}, res={res3}",
        )

        # 4) "저장소에 있음" + 가짜 run 호출 시 저장소에서 제거됨 -> certutil 인수 확인 및 파일 삭제
        _write_four_files()
        store_state_4 = [(der_bytes, "x509_asn", True)]
        ssl.enum_certificates = lambda store_name: list(store_state_4)
        run_calls_case4 = []

        def _fake_run_case4(args, **kwargs):
            run_calls_case4.append((list(args), kwargs))
            store_state_4.clear()
            return subprocess.CompletedProcess(args, 0, "", "")

        res4 = tls.remove_legacy(run=_fake_run_case4)
        cmd4 = [str(x) for x in run_calls_case4[0][0]] if run_calls_case4 else []
        cmd4_lower = [x.lower() for x in cmd4]
        args_ok_4 = (
            len(run_calls_case4) == 1
            and "-user" in cmd4
            and "-delstore" in cmd4
            and "root" in cmd4_lower
            and expected_serial_hex.lower() in cmd4_lower
        )
        files_gone_4 = not any(p.exists() for p in four_files)
        check(
            "S2-3 저장소에 있음(제거 성공) -> certutil 인수 확인 및 파일 삭제",
            args_ok_4
            and files_gone_4
            and isinstance(res4, dict)
            and res4.get("untrusted") is True
            and not res4.get("error"),
            f"cmd={cmd4}, files_gone={files_gone_4}, res={res4}",
        )

        # 5) "저장소에 있음" + 가짜 run 실패(저장소 그대로) -> 파일 삭제 안 됨, error 값 있음
        # 결함 시: 저장소 제거가 실패했는데도 ca.crt를 지워버려 재시도가 불가능해짐
        _write_four_files()
        store_state_5 = [(der_bytes, "x509_asn", True)]
        ssl.enum_certificates = lambda store_name: list(store_state_5)

        def _fake_run_case5(args, **kwargs):
            return subprocess.CompletedProcess(args, 1, "", "access denied")

        res5 = tls.remove_legacy(run=_fake_run_case5)
        files_kept_5 = all(p.exists() for p in four_files)
        check(
            "S2-3 저장소 제거 실패 시 -> 파일 삭제 안 됨, error 값 있음",
            files_kept_5
            and isinstance(res5, dict)
            and res5.get("untrusted") is False
            and bool(res5.get("error")),
            f"files_kept={files_kept_5}, res={res5}",
        )
    except Exception as e:
        check("S2 wst.tls 단위 시험 예외", False, repr(e))
    finally:
        for k, v in orig_attrs.items():
            setattr(tls, k, v)
        if orig_enum_certs is not None:
            ssl.enum_certificates = orig_enum_certs


# =====================================================================
# S3: server._check_websockets_version 판정 시험
# 가정: server.py가 최상위 실행 코드를 포함할 수 있으므로 AST에서 import·상수·함수 정의만 추출해 main 실행 없이 로드함
# =====================================================================
def _load_check_websockets_version():
    src = SERVER_PY.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(SERVER_PY))
    safe_body = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign))
    ]
    mod_ast = ast.Module(body=safe_body, type_ignores=[])
    ast.fix_missing_locations(mod_ast)
    ns = {"__file__": str(SERVER_PY), "__name__": "server_test_extracted"}
    exec(compile(mod_ast, str(SERVER_PY), "exec"), ns)
    return ns["_check_websockets_version"]


try:
    _check_ws_ver = _load_check_websockets_version()
    for bad_ver in ("17.3", "16.0", "17.4rc1", "17.4.dev0"):
        r = _check_ws_ver(bad_ver)
        check(
            f"S3 _check_websockets_version({bad_ver!r}) -> 오류 문자열 반환",
            isinstance(r, str) and len(r) > 0,
            repr(r),
        )
    for good_ver in ("17.4", "17.4.1", "18.0"):
        r = _check_ws_ver(good_ver)
        check(
            f"S3 _check_websockets_version({good_ver!r}) -> None",
            r is None,
            repr(r),
        )
except Exception as e:
    check("S3 _check_websockets_version 로드 및 실행", False, repr(e))


# =====================================================================
# S4: wst.tools.TftpServer · HttpServer 의 bind 기본값 "127.0.0.1"
# 결함 시: 기본값이 "0.0.0.0"이어서 같은 네트워크에 인증 없이 노출됨
# =====================================================================
for cls_name in ("TftpServer", "HttpServer"):
    try:
        cls = getattr(tools, cls_name)
        sig = inspect.signature(cls)
        default_bind = sig.parameters["bind"].default
        check(
            f"S4 wst.tools.{cls_name} bind 기본값 == '127.0.0.1'",
            default_bind == "127.0.0.1",
            f"default={default_bind!r}",
        )
    except Exception as e:
        check(f"S4 wst.tools.{cls_name} bind 기본값 == '127.0.0.1'", False, repr(e))


# =====================================================================
# S5: wst.sftp.read_ticket 1회용 소모 및 만료 티켓 제거
# 결함 시: DL_TICKETS.get()을 사용하여 두 번째 호출에도 파일이 다시 내려받아짐
# 가정: DL_TICKETS 항목 형식은 (sess, remote_path, expire_ts) 3-튜플을 기본으로 하되,
#       read_ticket 소스에 time.monotonic이 쓰이면 monotonic 기준 만료 시각을 넣음
# =====================================================================
class _FakeSftpFile:
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def prefetch(self, *args):   # Claude 수정(11/13): read_ticket이 prefetch() 호출
        pass

    def read(self, *args) -> bytes:
        return self._data


class _FakeSftpStat:
    def __init__(self, size: int):
        self.st_size = size


class _FakeSftpClient:
    def __init__(self, data: bytes):
        self._data = data

    def stat(self, path: str):
        return _FakeSftpStat(len(self._data))

    def open(self, path: str, mode: str = "rb"):
        return _FakeSftpFile(self._data)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakeSshClient:
    def __init__(self, data: bytes):
        self._data = data

    def open_sftp(self):
        return _FakeSftpClient(self._data)


class _FakeSess(dict):   # Claude 수정(11/13): 실제 세션은 dict(sess["client"])
    def __init__(self, data: bytes):
        super().__init__(client=_FakeSshClient(data))
        self.client = self["client"]


try:
    payload = b"hello_wst_b1_ticket"
    fake_sess = _FakeSess(payload)
    try:
        rt_src = inspect.getsource(sftp.read_ticket)
    except OSError:
        rt_src = ""
    now_fn = time.monotonic if "monotonic" in rt_src else time.time

    sftp.DL_TICKETS.clear()
    # Claude 수정(11/13): agy의 3칸 가정 대신 실제 API make_ticket(sess, 경로, 이름)으로 티켓 생성
    tok_valid = sftp.make_ticket(fake_sess, "/remote/dir/sample.txt", "sample.txt")

    first_res = sftp.read_ticket(tok_valid)
    second_res = sftp.read_ticket(tok_valid)

    check(
        "S5 read_ticket 첫 호출 -> (이름, 내용) 반환",
        first_res == ("sample.txt", payload),
        repr(first_res),
    )
    check(
        "S5 read_ticket 두 번째 호출 -> None (1회용 소모)",
        second_res is None and tok_valid not in sftp.DL_TICKETS,
        f"second={second_res!r}, remaining={list(sftp.DL_TICKETS.keys())}",
    )

    tok_expired = sftp.make_ticket(fake_sess, "/remote/dir/expired.txt", "expired.txt")
    sftp.DL_TICKETS[tok_expired] = (*sftp.DL_TICKETS[tok_expired][:3], 0.0)
    exp_res = sftp.read_ticket(tok_expired)
    check(
        "S5 만료 티켓 호출 -> None 및 DL_TICKETS에서 제거",
        exp_res is None and tok_expired not in sftp.DL_TICKETS,
        f"exp_res={exp_res!r}, remaining={list(sftp.DL_TICKETS.keys())}",
    )
except Exception as e:
    check("S5 wst.sftp.read_ticket 단위 시험", False, repr(e))


print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
