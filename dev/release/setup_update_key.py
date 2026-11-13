"""업데이트 서명 키를 만들어 GitHub `release` 환경 Secret(WST_UPDATE_KEY)에 바로 등록하고,
공개키를 wst/update.py에 넣는다. 비밀키는 화면·파일 어디에도 남기지 않는다.

python dev/release/setup_update_key.py            # 환경 만들기(승인자=토큰 주인, v* 태그만) + 키 등록
python dev/release/setup_update_key.py --rotate   # 이미 공개키가 있어도 새 키로 교체(이전 버전 사용자는 수동 설치 필요)

토큰은 `git credential fill`(github.com)에서 읽는다. 필요한 권한: 저장소 관리(환경·Secret).
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nacl.public import PublicKey, SealedBox

REPO = "rorena15/web-ssh-terminal"
ENV = "release"
ROOT = Path(__file__).resolve().parents[2]
UPDATE_PY = ROOT / "wst" / "update.py"


def token():
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("git 자격 증명에서 GitHub 토큰을 찾지 못했습니다")


def api(tok, method, path, body=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "wst-release-setup"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rotate", action="store_true")
    a = ap.parse_args()

    src = UPDATE_PY.read_text(encoding="utf-8")
    cur = re.search(r'^UPDATE_PUBKEY = "([^"]*)"', src, re.M)
    if not cur:
        raise SystemExit("wst/update.py에서 UPDATE_PUBKEY 줄을 찾지 못했습니다")
    if cur.group(1) and not a.rotate:
        raise SystemExit("이미 공개키가 있습니다. 교체하려면 --rotate (이전 버전 사용자는 수동 설치 필요)")

    tok = token()
    st, me = api(tok, "GET", "/user")
    if st != 200:
        raise SystemExit(f"토큰 확인 실패: {st}")
    print("계정:", me["login"])

    st, _ = api(tok, "PUT", f"/repos/{REPO}/environments/{ENV}", {
        "reviewers": [{"type": "User", "id": me["id"]}],
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}})
    print("환경 release(승인자 지정):", st)
    if st not in (200, 201):
        raise SystemExit("환경 설정 실패 — 토큰에 저장소 관리 권한이 필요합니다")
    def policies():
        st, pol = api(tok, "GET", f"/repos/{REPO}/environments/{ENV}/deployment-branch-policies?per_page=100")
        if st != 200:
            raise SystemExit(f"배포 규칙 조회 실패: {st}")
        if pol.get("total_count", 0) > len(pol.get("branch_policies", [])):
            raise SystemExit("배포 규칙이 100개를 넘습니다 — 직접 확인하세요")
        return {(p.get("type", "branch"), p.get("name")) for p in pol.get("branch_policies", [])}

    rules = policies()
    if not rules:
        st, _ = api(tok, "POST", f"/repos/{REPO}/environments/{ENV}/deployment-branch-policies", {"name": "v*", "type": "tag"})
        print("배포 허용 태그 v*:", st)
        if st not in (200, 201):
            raise SystemExit("배포 규칙 설정 실패")
        rules = policies()
    if rules != {("tag", "v*")}:
        raise SystemExit(f"release 환경 배포 규칙이 'tag v*' 하나가 아닙니다: {sorted(rules)} — 정리 후 다시 실행하세요")
    print("배포 규칙: tag v* 하나만")

    st, _ = api(tok, "GET", f"/repos/{REPO}/environments/{ENV}/secrets/WST_UPDATE_KEY")
    if st == 200 and not a.rotate:
        raise SystemExit("release 환경에 WST_UPDATE_KEY가 이미 있습니다. 교체하려면 --rotate")
    if st not in (200, 404):
        raise SystemExit(f"기존 Secret 확인 실패: {st}")

    st, pk = api(tok, "GET", f"/repos/{REPO}/environments/{ENV}/secrets/public-key")
    if st != 200:
        raise SystemExit(f"Secret 공개키 조회 실패: {st}")

    key = Ed25519PrivateKey.generate()
    priv_b64 = base64.b64encode(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                  serialization.NoEncryption()))
    sealed = SealedBox(PublicKey(base64.b64decode(pk["key"]))).encrypt(priv_b64)
    del priv_b64
    pub_b64 = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    del key

    # 공개키를 먼저 원자적으로 기록 → Secret 등록 → 등록 실패면 되돌림. 응답만 끊긴 경우에도 양쪽이 새 키로 맞는다.
    def write(text):
        tmp = UPDATE_PY.with_suffix(".py.tmp")
        tmp.write_text(text, encoding="utf-8", newline="")
        tmp.replace(UPDATE_PY)

    print("공개키:", pub_b64)
    write(src.replace(cur.group(0), f'UPDATE_PUBKEY = "{pub_b64}"', 1))
    try:
        st, _ = api(tok, "PUT", f"/repos/{REPO}/environments/{ENV}/secrets/WST_UPDATE_KEY",
                    {"encrypted_value": base64.b64encode(sealed).decode(), "key_id": pk["key_id"]})
    except Exception:
        print("Secret 등록 응답을 받지 못했습니다. 공개키는 새 값으로 두었습니다 — GitHub에서 WST_UPDATE_KEY 갱신 시각을 확인하고,"
              " 갱신되지 않았으면 --rotate로 다시 실행하세요")
        raise
    print("Secret WST_UPDATE_KEY 등록:", st)
    if st not in (201, 204):
        write(src)
        raise SystemExit("Secret 등록 실패 — wst/update.py 공개키를 원래대로 되돌렸습니다")
    print("완료: wst/update.py에 공개키를 넣었습니다")


if __name__ == "__main__":
    main()
