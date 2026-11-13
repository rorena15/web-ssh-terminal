"""이전 버전이 설치한 로컬 CA의 신뢰 등록과 파일 정리."""
import ssl
import subprocess
import sys

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization

from wst.common import BASE

CERTS = BASE / "certs"
CA_CRT, CA_KEY = CERTS / "ca.crt", CERTS / "ca.key"
SRV_CRT, SRV_KEY = CERTS / "server.crt", CERTS / "server.key"


def legacy_present() -> bool:
    return any(p.exists() for p in (CA_CRT, CA_KEY, SRV_CRT, SRV_KEY))


def legacy_trusted() -> bool | None:
    if not CA_CRT.exists():
        return False
    if sys.platform != "win32":
        return None
    try:
        der = x509.load_pem_x509_certificate(CA_CRT.read_bytes()).public_bytes(serialization.Encoding.DER)
    except (ValueError, UnsupportedAlgorithm):
        return False
    return any(c[0] == der for c in ssl.enum_certificates("ROOT"))


def remove_legacy(run=subprocess.run) -> dict:
    result = {"untrusted": False, "deleted": [], "error": None}
    try:
        trusted = legacy_trusted()
        if trusted:
            serial = x509.load_pem_x509_certificate(CA_CRT.read_bytes()).serial_number
            r = run(["certutil", "-user", "-delstore", "Root", format(serial, "x")],
                    capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=60)
            trusted = legacy_trusted()
            if r.returncode != 0 or trusted is not False:
                result["error"] = "신뢰 저장소에서 CA를 제거하지 못했습니다"
                return result
        if trusted is None:
            result["error"] = "Windows 외 환경에서는 신뢰 저장소 제거 여부를 확인할 수 없습니다"
            return result
        result["untrusted"] = True
        for path in (CA_KEY, SRV_KEY, SRV_CRT, CA_CRT):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            result["deleted"].append(path.name)
        try:
            CERTS.rmdir()
        except OSError:
            pass
    except Exception:
        # 인증서·개인키 내용이나 외부 명령 출력을 오류에 포함하지 않는다.
        result["error"] = "이전 CA 정리 중 오류가 발생했습니다"
    return result
