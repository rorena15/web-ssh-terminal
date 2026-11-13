"""11/13 업데이트 서명 키 여러 개·예비 키 파일 시험(Claude 검증). python t_update_keys.py [저장소 루트]
- 주 키·예비 키 어느 쪽 서명이든 통과, 모르는 키 거부, 형식 틀린 키 설정은 오류, 빈 예비 키 무시
- make_backup_key: 비밀번호 확인·12자 미만 거부·덮어쓰기 거부, 저장 뒤 복호화, 출력에 비밀 없음
- sign_manifest --key-file: 예비 키로 서명하고 UPDATE_PUBKEYS로 자체 검증, 틀린 비밀번호는 비밀 노출 없는 오류
"""
import base64
import contextlib
import getpass
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wst import update  # noqa: E402
from dev.release import make_backup_key as mbk  # noqa: E402
from dev.release import sign_manifest as sm  # noqa: E402

R = []


def check(name, ok, info=""):
    R.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f" - {info}" if info else ""))


def pub(k):
    return base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def manifest(ver="9.0.0"):
    m = {"format": 1, "version": ver, "build": 1, "published": "x",
         "zip": {"name": "a.zip", "size": 10, "sha256": "0" * 64},
         "files": [{"path": "W.S.T.exe", "size": 1, "sha256": "0" * 64, "data_offset": 0, "compress_size": 1, "method": 0}]}
    return json.dumps(m).encode()


primary, backup, stranger = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
keys = (pub(primary), pub(backup))
raw = manifest()

def ok_with(k, keyset):
    try:
        update.verify_manifest(raw, k.sign(raw), "1.0.0", keyset)
        return True
    except update.UpdateError:
        return False

check("주 키 서명 통과", ok_with(primary, keys))
check("예비 키 서명 통과", ok_with(backup, keys))
check("모르는 키 서명 거부", not ok_with(stranger, keys))
check("빈 예비 키 무시(주 키만)", ok_with(primary, (pub(primary), "")) and not ok_with(backup, (pub(primary), "")))
try:
    update.verify_manifest(raw, primary.sign(raw), "1.0.0", (pub(primary), "not-base64!!"))
    check("형식 틀린 키 설정 → 오류", False)
except update.UpdateError:
    check("형식 틀린 키 설정 → 오류", True)
check("문자열 하나도 허용(기존 호환)", ok_with(primary, pub(primary)))

# make_backup_key
tmp = Path(tempfile.mkdtemp(prefix="wst_keys_"))
pw = "correct horse battery"
out = tmp / "backup.json"


def run_make(path, answers):
    it = iter(answers)
    orig = getpass.getpass
    getpass.getpass = lambda prompt="": next(it)
    buf = io.StringIO()
    old_argv = sys.argv
    sys.argv = ["make_backup_key.py", str(path)]
    try:
        with contextlib.redirect_stdout(buf):
            mbk.main()
        return 0, buf.getvalue()
    except SystemExit as e:
        return e.code, buf.getvalue()
    finally:
        getpass.getpass = orig
        sys.argv = old_argv


code, _ = run_make(tmp / "short.json", ["short", "short"])
check("12자 미만 비밀번호 거부", code not in (0, None) and not (tmp / "short.json").exists())
code, _ = run_make(tmp / "mismatch.json", [pw, pw + "x"])
check("확인 불일치 거부", code not in (0, None) and not (tmp / "mismatch.json").exists())
code, text = run_make(out, [pw, pw])
saved = json.loads(out.read_text(encoding="utf-8"))
check("예비 키 파일 생성", code in (0, None) and saved["format"] == "wst-backup-key-1")
key = mbk.load_backup_key(out, pw)
check("올바른 비밀번호로 복호화·공개키 일치", pub(key) == saved["pubkey"])
priv_b64 = base64.b64encode(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()
check("출력에 비밀키·비밀번호 없음", priv_b64 not in text and pw not in text and saved["pubkey"] in text)
check("파일에 평문 비밀키 없음", priv_b64 not in out.read_text(encoding="utf-8"))
code, _ = run_make(out, [pw, pw])
check("이미 있는 파일 덮어쓰기 거부", code not in (0, None) and json.loads(out.read_text(encoding="utf-8")) == saved)
try:
    mbk.load_backup_key(out, "wrong password!!")
    check("틀린 비밀번호 거부", False)
except ValueError as e:
    check("틀린 비밀번호 거부·메시지에 비밀 없음", pw not in str(e) and priv_b64 not in str(e), str(e))

# sign_manifest --key-file
zipf = tmp / "a.zip"
zipf.write_bytes(b"0123456789")
m = json.loads(raw)
m["zip"]["sha256"] = hashlib.sha256(b"0123456789").hexdigest()
mf = tmp / "manifest.json"
mf.write_bytes(json.dumps(m).encode())
sig = tmp / "manifest.json.sig"
orig_keys, orig_gp = sm.UPDATE_PUBKEYS, getpass.getpass
try:
    sm.UPDATE_PUBKEYS = (pub(primary), saved["pubkey"])
    getpass.getpass = lambda prompt="": pw
    sm.sign_manifest(mf, sig, zipf, "v9.0.0", out)
    ok = sig.exists() and ok_with.__code__ and update.verify_manifest(mf.read_bytes(), sig.read_bytes(), "1.0.0", sm.UPDATE_PUBKEYS)
    check("--key-file 예비 키로 서명·자체 검증", bool(ok))
    sig.unlink()
    sm.UPDATE_PUBKEYS = (pub(primary), "")
    try:
        sm.sign_manifest(mf, sig, zipf, "v9.0.0", out)
        check("예비 공개키가 앱에 없으면 서명 거부", False)
    except Exception:
        check("예비 공개키가 앱에 없으면 서명 거부", not sig.exists())
    getpass.getpass = lambda prompt="": "wrong password!!"
    sm.UPDATE_PUBKEYS = (pub(primary), saved["pubkey"])
    try:
        sm.sign_manifest(mf, sig, zipf, "v9.0.0", out)
        check("틀린 비밀번호 → 서명 안 함", False)
    except ValueError:
        check("틀린 비밀번호 → 서명 안 함", not sig.exists())
finally:
    sm.UPDATE_PUBKEYS, getpass.getpass = orig_keys, orig_gp

print(f"\n{sum(R)}/{len(R)} 통과")
sys.exit(0 if all(R) else 1)
