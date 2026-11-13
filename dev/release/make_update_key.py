"""키를 파일에 저장하지 않고 출력한다. 비밀키는 WST_UPDATE_KEY Secret에 넣는다."""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


if __name__ == "__main__":
    key = Ed25519PrivateKey.generate()
    print("WST_UPDATE_KEY (GitHub Actions Secret):")
    print(base64.b64encode(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode())
    print("UPDATE_PUBKEY (wst/update.py):")
    print(base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())
