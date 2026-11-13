"""CI 환경의 키로 manifest 원본 바이트를 서명하고 즉시 자체 검증한다."""
import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dev.release.make_backup_key import load_backup_key
from wst.update import UPDATE_PUBKEYS, verify_manifest


def sign_manifest(manifest: Path, output: Path, archive: Path, tag: str, key_file: Path | None = None):
    raw = manifest.read_bytes()
    m = json.loads(raw)
    if not tag.startswith("v") or m["version"] != tag[1:]:
        raise ValueError("Tag and manifest version differ")
    with archive.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if size != m["zip"]["size"] or digest != m["zip"]["sha256"].lower():
        raise ValueError("Zip and manifest size/SHA-256 differ")
    if key_file is not None:
        key = load_backup_key(key_file, getpass.getpass("예비 키 비밀번호: "))
    else:
        try:
            key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(os.environ["WST_UPDATE_KEY"], validate=True))
        except (KeyError, ValueError, TypeError):
            raise ValueError("WST_UPDATE_KEY 설정 오류") from None
    sig = key.sign(raw)
    key.public_key().verify(sig, raw)
    # 배포된 앱에 내장할 공개키와 CI 키도 반드시 일치해야 한다.
    if not any(UPDATE_PUBKEYS):
        raise ValueError("wst/update.py의 UPDATE_PUBKEYS를 먼저 설정하세요")
    verify_manifest(raw, sig, "0.0.0", UPDATE_PUBKEYS)
    output.write_bytes(sig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=Path("manifest.json"))
    ap.add_argument("--output", type=Path, default=Path("manifest.json.sig"))
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--key-file", type=Path, help="비밀번호로 암호화된 예비 키 파일")
    args = ap.parse_args()
    try:
        sign_manifest(args.manifest, args.output, args.zip, args.tag, args.key_file)
    except (KeyboardInterrupt, EOFError):
        raise SystemExit("서명을 취소했습니다") from None
    except ValueError as e:
        raise SystemExit(str(e)) from None
