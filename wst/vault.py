"""비밀번호 저장소.

- 저장: data/vault.bin = DPAPI(CurrentUser)로 암호화 → 이 PC의 이 Windows 계정에서만 풀림.
- 마스터 비밀번호(선택): 설정하면 내용을 scrypt+AES-GCM으로 한 번 더 감싼 뒤 DPAPI. 서버를 켤 때마다 잠금 해제 필요.
- 브라우저에는 비밀번호를 보내지 않는다. 브라우저는 "어떤 user@host:port가 저장돼 있는지"만 알고,
  실제 비밀번호는 sshconn.connect_one / RDP 실행 때 서버 안에서만 꺼내 쓴다.
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import threading

from wst import common

PATH = common.DATA / "vault.bin"
_ENTROPY = b"rorena15.WST.vault.v1"
_lock = threading.Lock()


class Locked(Exception):
    """마스터 비밀번호로 잠겨 있음."""


# ── DPAPI ─────────────────────────────────────────────────
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(b):
    buf = ctypes.create_string_buffer(b, len(b))
    return _Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(data, protect, entropy=None):
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    src, _k1 = _blob(data)
    ent, _k2 = _blob(_ENTROPY if entropy is None else entropy)
    out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), "webssh" if protect else None, ctypes.byref(ent), None, None,
            0x1, ctypes.byref(out))                     # 0x1 = CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise OSError("DPAPI 실패 (다른 Windows 계정에서 만든 파일일 수 있음)")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _write_body(body):
    PATH.parent.mkdir(exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_bytes(_dpapi(body, True))
    os.replace(tmp, PATH)


def _read_body():
    data = PATH.read_bytes()
    return _dpapi(data, False)


# ── 마스터 비밀번호 (scrypt + AES-GCM) ─────────────────────
def _kdf(master, salt):
    return hashlib.scrypt(master.encode("utf-8"), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 << 20, dklen=32)


def _seal(obj, master):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = os.urandom(16), os.urandom(12)
    ct = AESGCM(_kdf(master, salt)).encrypt(nonce, json.dumps(obj).encode(), b"vault")
    return b"M1" + salt + nonce + ct


def _open(raw, master):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce, ct = raw[2:18], raw[18:30], raw[30:]
    try:
        return json.loads(AESGCM(_kdf(master, salt)).decrypt(nonce, ct, b"vault"))
    except InvalidTag:
        raise ValueError("마스터 비밀번호가 틀렸습니다")


# ── 저장소 ────────────────────────────────────────────────
class Vault:
    def __init__(self):
        self.items = None          # {"user@host:port": {"password": ..., "passphrase": ...}} — 잠겨 있으면 None
        self.master = None         # 잠금 해제한 마스터 비밀번호 (메모리에만)
        self.has_master = False
        self.raw = None
        self._load()

    def _load(self):
        if not PATH.exists():
            self.items = {}
            return
        try:
            raw = _read_body()
        except OSError:
            import time
            PATH.replace(PATH.with_suffix(time.strftime(".unreadable-%Y%m%d-%H%M%S.bin")))      # 다른 계정/PC에서 가져온 파일 → 보관하고 새로 시작
            self.items = {}
            return
        if raw.startswith(b"M1"):
            self.has_master, self.raw = True, raw
        else:
            self.items = json.loads(raw or b"{}")

    def _save(self):
        body = _seal(self.items, self.master) if self.has_master else json.dumps(self.items).encode()
        _write_body(body)
        if self.has_master:
            self.raw = body              # 잠갔다 풀 때 최신 내용으로 열리게

    # 상태 (브라우저에 보내도 되는 것만)
    def status(self):
        with _lock:
            locked = self.items is None
            return {"locked": locked, "master": self.has_master,
                    "keys": [] if locked else sorted(k for k, v in self.items.items() if v.get("password") or v.get("passphrase"))}

    def unlock(self, master):
        with _lock:
            if self.items is not None:
                return
            self.items = _open(self.raw, master)
            self.master = master

    def verify(self, master):
        """마스터 비밀번호가 맞는지만 확인 (화면 잠금 해제용)."""
        if not self.has_master:
            return False
        raw = self.raw or _read_body()
        try:
            _open(raw, master)
            return True
        except ValueError:
            return False

    def lock(self):
        with _lock:
            if self.has_master:
                self.items, self.master = None, None

    def get(self, key):
        with _lock:
            if self.items is None:
                return {}
            return dict(self.items.get(key) or {})

    def set(self, key, **fields):
        with _lock:
            if self.items is None:
                raise Locked("비밀번호 저장소가 잠겨 있습니다")
            cur = self.items.setdefault(key, {})
            for k, v in fields.items():
                if v:
                    cur[k] = v
                else:
                    cur.pop(k, None)
            if not cur:
                self.items.pop(key, None)
            self._save()

    def delete(self, key):
        self.set(key, password=None, passphrase=None)

    def set_master(self, old, new):
        """마스터 비밀번호 설정/변경/해제(new 비우기)."""
        with _lock:
            if self.has_master:
                if self.items is None:
                    self.items = _open(self.raw, old or "")
                elif old != self.master:
                    _open(_seal({}, self.master), old or "")       # 틀리면 ValueError
            self.has_master, self.master = bool(new), new or None
            self._save()
            if self.has_master:
                self.raw = _dpapi(PATH.read_bytes(), False)


VAULT = Vault() if os.name == "nt" else None


def key_of(p, prefix=""):
    return f'{prefix}{p.get("username", "")}@{p["host"]}:{int(p.get("port") or 22)}'


def fill(p):
    """SSH 홉 매개변수 p에 비밀번호/키 암호가 비어 있으면 저장소에서 채움. 채웠으면 True."""
    if not VAULT or p.get("noSaved") or not common.LOCAL_MODE:   # 외부 바인딩이면 저장된 비밀번호를 쓰지 않음
        return False
    v = VAULT.get(key_of(p))
    used = False
    if not p.get("password") and v.get("password") and p.get("auth", "password") == "password":
        p["password"], used = v["password"], True
    if not p.get("passphrase") and v.get("passphrase"):
        p["passphrase"], used = v["passphrase"], True
    return used


# ── RDP: 저장된 비밀번호를 Windows 자격 증명(TERMSRV/호스트)에 넣어 mstsc가 묻지 않게 ──
class _Cred(ctypes.Structure):
    _fields_ = [("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR), ("Comment", wt.LPWSTR),
                ("LastWritten", wt.FILETIME), ("CredentialBlobSize", wt.DWORD), ("CredentialBlob", ctypes.c_void_p),
                ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wt.LPWSTR), ("UserName", wt.LPWSTR)]


def delete_rdp_cred(host):
    ctypes.windll.advapi32.CredDeleteW(f"TERMSRV/{host}", 2, 0)       # 없으면 실패해도 무시


def write_rdp_cred(host, username, password):
    """CredWriteW로 등록 (명령줄 cmdkey는 비밀번호가 프로세스 인수에 드러나므로 쓰지 않음). 로그온 세션 동안만 유지."""
    blob = password.encode("utf-16-le")
    buf = ctypes.create_string_buffer(blob, len(blob))
    c = _Cred()
    c.Type = 2                      # CRED_TYPE_DOMAIN_PASSWORD
    c.TargetName = f"TERMSRV/{host}"
    c.UserName = username
    c.CredentialBlobSize = len(blob)
    c.CredentialBlob = ctypes.cast(buf, ctypes.c_void_p)
    c.Persist = 1                   # CRED_PERSIST_SESSION
    if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(c), 0):
        raise OSError(f"자격 증명 등록 실패 ({ctypes.GetLastError()})")
