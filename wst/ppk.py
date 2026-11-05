"""PuTTY .ppk 개인키 → OpenSSH PEM 문자열 (세션을 가져오면 키가 .ppk인 경우가 많음).

지원: PPK v2 (암호 없음 / aes256-cbc), PPK v3 (암호 없음). v3 + 암호(Argon2)는 변환 안내.
키 종류: ssh-rsa, ssh-ed25519, ecdsa-sha2-nistp256/384/521.
"""
import base64
import hashlib
import hmac
import struct

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class PpkError(ValueError):
    pass


class NeedPassphrase(Exception):
    pass


def _parse(text):
    lines = text.replace("\r\n", "\n").split("\n")
    h, i = {}, 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if ": " not in line:
            continue
        k, v = line.split(": ", 1)
        if k in ("Public-Lines", "Private-Lines"):
            n = int(v)
            h[k.split("-")[0]] = base64.b64decode("".join(lines[i:i + n]))
            i += n
        else:
            h[k] = v
    return h


class _R:
    def __init__(self, b):
        self.b, self.o = b, 0

    def str(self):
        n = struct.unpack(">I", self.b[self.o:self.o + 4])[0]
        v = self.b[self.o + 4:self.o + 4 + n]
        self.o += 4 + n
        return v

    def mpint(self):
        return int.from_bytes(self.str(), "big", signed=True)


def _sstr(b):
    return struct.pack(">I", len(b)) + b


def ppk_to_openssh(text, passphrase=None):
    h = _parse(text)
    ver = 3 if "PuTTY-User-Key-File-3" in h else 2 if "PuTTY-User-Key-File-2" in h else 0
    if not ver:
        raise PpkError("지원하지 않는 PuTTY 키 형식입니다 (v2/v3만 지원)")
    algo = h.get(f"PuTTY-User-Key-File-{ver}")
    enc = h.get("Encryption", "none")
    pub, priv = h["Public"], h["Private"]
    if enc != "none":
        if ver == 3:
            raise PpkError("PuTTY v3 암호 키(Argon2)는 직접 읽을 수 없습니다. PuTTYgen → Conversions → Export OpenSSH key로 변환하세요.")
        if not passphrase:
            raise NeedPassphrase()
        pw = passphrase.encode("utf-8")
        key = hashlib.sha1(b"\0\0\0\0" + pw).digest() + hashlib.sha1(b"\0\0\0\1" + pw).digest()
        d = Cipher(algorithms.AES(key[:32]), modes.CBC(b"\0" * 16)).decryptor()
        priv = d.update(priv) + d.finalize()
    # 무결성(MAC) 확인 — v2: HMAC-SHA1(key=SHA1("putty-private-key-file-mac-key"+pw))
    if ver == 2:
        mk = hashlib.sha1(b"putty-private-key-file-mac-key" + (passphrase or "").encode("utf-8") if enc != "none" else b"putty-private-key-file-mac-key").digest()
        data = _sstr(algo.encode()) + _sstr(enc.encode()) + _sstr(h.get("Comment", "").encode()) + _sstr(pub) + _sstr(priv)
        if not hmac.compare_digest(hmac.new(mk, data, hashlib.sha1).hexdigest(), h.get("Private-MAC", "")):
            raise (NeedPassphrase if passphrase else PpkError)("키 암호가 틀렸거나 키 파일이 손상되었습니다")
    pr, vr = _R(pub), _R(priv)
    pr.str()                                    # 알고리즘 이름
    if algo == "ssh-rsa":
        e, n = pr.mpint(), pr.mpint()
        dd, p, q, iqmp = vr.mpint(), vr.mpint(), vr.mpint(), vr.mpint()
        k = rsa.RSAPrivateNumbers(p, q, dd, dd % (p - 1), dd % (q - 1), iqmp, rsa.RSAPublicNumbers(e, n)).private_key()
    elif algo == "ssh-ed25519":
        k = ed25519.Ed25519PrivateKey.from_private_bytes(vr.str()[-32:])
    elif algo.startswith("ecdsa-sha2-"):
        curve = {"nistp256": ec.SECP256R1(), "nistp384": ec.SECP384R1(), "nistp521": ec.SECP521R1()}[pr.str().decode()]
        k = ec.derive_private_key(vr.mpint(), curve)
    else:
        raise PpkError(f"지원하지 않는 키 종류: {algo}")
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                           serialization.NoEncryption()).decode()
