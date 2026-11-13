"""오프라인 예비 서명 키를 비밀번호로 암호화해 저장한다."""
import argparse
import base64
import getpass
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

AAD = b"WST-backup-key-v1"
KDF = {"name": "scrypt", "n": 2**17, "r": 8, "p": 1}


def _derive(password, salt):
    return Scrypt(salt=salt, length=32, n=KDF["n"], r=KDF["r"], p=KDF["p"]).derive(password.encode("utf-8"))


def _public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def load_backup_key(path, password):
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved["format"] != "wst-backup-key-1":
            raise ValueError
        kdf = saved["kdf"]
        if any(type(kdf[name]) is not type(value) or kdf[name] != value for name, value in KDF.items()):
            raise ValueError
        salt, nonce, ciphertext, public = (
            base64.b64decode(value, validate=True)
            for value in (kdf["salt"], saved["nonce"], saved["ciphertext"], saved["pubkey"])
        )
        if (len(salt), len(nonce), len(ciphertext), len(public)) != (16, 12, 48, 32):
            raise ValueError
        raw = AESGCM(_derive(password, salt)).decrypt(nonce, ciphertext, AAD)
        key = Ed25519PrivateKey.from_private_bytes(raw)
        if _public(key) != public:
            raise ValueError
        return key
    except Exception:
        raise ValueError("예비 키 파일을 복호화할 수 없습니다. 파일과 비밀번호를 확인하세요") from None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit("이미 있는 파일에는 저장할 수 없습니다")
    password = getpass.getpass("비밀번호(12자 이상): ")
    confirm = getpass.getpass("비밀번호 확인: ")
    if len(password) < 12 or password != confirm:
        raise SystemExit("비밀번호는 12자 이상이며 두 입력이 일치해야 합니다")
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    salt, nonce = os.urandom(16), os.urandom(12)
    ciphertext = AESGCM(_derive(password, salt)).encrypt(nonce, raw, AAD)
    public = base64.b64encode(_public(key)).decode("ascii")
    saved = {
        "format": "wst-backup-key-1",
        "kdf": {**KDF, "salt": base64.b64encode(salt).decode("ascii")},
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "pubkey": public,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(saved, stream, indent=2)
        stream.write("\n")
    if _public(load_backup_key(args.output, password)) != _public(key):
        raise ValueError("저장한 예비 키의 공개키가 일치하지 않습니다")
    print("공개키:", public)
    print("이 파일과 비밀번호를 따로 보관하세요")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        raise SystemExit("예비 키 생성을 취소했습니다") from None
    except Exception:
        raise SystemExit("예비 키 생성 또는 저장 후 검증에 실패했습니다") from None
