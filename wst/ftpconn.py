"""FTP / FTPS 세션: ftplib를 paramiko SFTPClient처럼 보이게 감싸서 sftp.py의 파일 탐색기를 그대로 쓴다.

/ftp WebSocket = 로그인 후 SESSIONS에 {"client": FtpClient} 등록 → 브라우저 SftpPanel이 /sftp?sid=… 로 붙음.
경로는 sftp.py와 같은 규칙(서버 바이트 경로)을 쓰므로 ftplib 인코딩을 latin-1로 두고 바이트를 그대로 왕복시킨다.
"""
import asyncio
import datetime as dt
import ftplib
import io
import json
import secrets
import ssl
import stat as st

from websockets.exceptions import ConnectionClosed

from wst import common
from wst import vault
from wst.term import ENCODINGS


class Attr:
    def __init__(self, name=b"", mode=0, size=0, mtime=0, owner="", group=""):
        self.filename = name.decode("utf-8", "surrogateescape") if isinstance(name, bytes) else name
        self.st_mode, self.st_size, self.st_mtime = mode, size, mtime
        self.st_uid = self.st_gid = 0
        perm = st.filemode(mode)
        self.longname = f"{perm} 1 {owner or '-'} {group or '-'} {size} x x x {self.filename}" if owner else ""


def _b(path):          # sftp.py가 주는 bytes 경로 → ftplib 명령 문자열 (latin-1로 바이트 그대로)
    return path.decode("latin-1") if isinstance(path, bytes) else path


def _mtime(s):
    try:
        return dt.datetime.strptime(s[:14], "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc).timestamp()
    except Exception:
        return 0


_MON = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def _parse_list(line):
    """유닉스 ls -l 형식 한 줄 → Attr (MLSD를 못 쓰는 서버용). 윈도우 IIS 형식도 대충 처리."""
    f = line.split(None, 8)
    if len(f) >= 9 and f[0][0] in "-dlbcps":
        perm = f[0]
        mode = {"d": st.S_IFDIR, "l": st.S_IFLNK}.get(perm[0], st.S_IFREG)
        for i, c in enumerate(perm[1:10]):
            if c not in "-STl":
                mode |= 1 << (8 - i)
        name = f[8].split(" -> ")[0] if perm[0] == "l" else f[8]
        try:
            mon, day = _MON[f[5]], int(f[6])
            if ":" in f[7]:
                y = dt.date.today().year
                h, mi = map(int, f[7].split(":"))
                t = dt.datetime(y, mon, day, h, mi)
                if t > dt.datetime.now() + dt.timedelta(days=1):
                    t = t.replace(year=y - 1)
            else:
                t = dt.datetime(int(f[7]), mon, day)
            mtime = t.timestamp()
        except Exception:
            mtime = 0
        return Attr(name.encode("latin-1"), mode, int(f[4]) if f[4].isdigit() else 0, mtime, f[2], f[3])
    f = line.split(None, 3)                        # 10-31-24  09:15AM  <DIR>  name
    if len(f) == 4:
        isdir = f[2] == "<DIR>"
        return Attr(f[3].encode("latin-1"), (st.S_IFDIR | 0o755) if isdir else (st.S_IFREG | 0o644),
                    0 if isdir else int(f[2]) if f[2].isdigit() else 0)
    return None


class _File:
    """sftp.open() 흉내: 데이터 연결 하나 = 파일 하나."""

    def __init__(self, ftp, path, mode, attr):
        self.ftp, self.mode, self.attr = ftp, mode, attr
        self.conn = ftp.transfercmd(("RETR " if "r" in mode else "STOR ") + _b(path))
        self.buf = b""

    def prefetch(self, *a):
        pass

    def set_pipelined(self, *a):
        pass

    def stat(self):
        return self.attr

    def read(self, n=-1):
        if n is None or n < 0:
            chunks = [self.buf]
            self.buf = b""
            while d := self.conn.recv(65536):
                chunks.append(d)
            return b"".join(chunks)
        while len(self.buf) < n:
            d = self.conn.recv(max(65536, n))
            if not d:
                break
            self.buf += d
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def write(self, data):
        self.conn.sendall(data)

    def close(self):
        if self.conn:
            try:
                if isinstance(self.conn, ssl.SSLSocket):
                    self.conn.unwrap()
            except Exception:
                pass
            self.conn.close()
            self.conn = None
            self.ftp.voidresp()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FtpSftp:
    """paramiko SFTPClient에서 sftp.py가 쓰는 메서드만."""

    def __init__(self, p):
        self.ftp = _login(p)
        feats = ""
        try:
            feats = self.ftp.sendcmd("FEAT").upper()
        except ftplib.all_errors:
            pass
        self.mlsd = "MLST" in feats

    def normalize(self, path):
        path = _b(path)
        if path in (".", ""):
            path = self.ftp.pwd()
        elif not path.startswith("/"):
            path = self.ftp.pwd().rstrip("/") + "/" + path
        # latin-1(바이트 그대로) → sftp.py 규칙(utf-8 + surrogateescape) 문자열. 그대로 두면 한글이 두 번 인코딩됨
        return path.encode("latin-1").decode("utf-8", "surrogateescape")

    def listdir_attr(self, path):
        path = _b(path)
        out = []
        if self.mlsd:
            for name, f in self.ftp.mlsd(path, facts=["type", "size", "modify", "unix.mode", "unix.owner", "unix.group", "perm"]):
                if name in (".", "..") or f.get("type") in ("cdir", "pdir"):
                    continue
                isdir = f.get("type") == "dir"
                mode = int(f["unix.mode"], 8) if f.get("unix.mode") else (0o755 if isdir else 0o644)
                mode |= st.S_IFDIR if isdir else st.S_IFLNK if "slink" in f.get("type", "") else st.S_IFREG
                out.append(Attr(name.encode("latin-1"), mode, int(f.get("size") or 0), _mtime(f.get("modify", "")),
                                f.get("unix.owner", ""), f.get("unix.group", "")))
            return out
        lines = []
        self.ftp.retrlines("LIST -a " + path if path else "LIST -a", lines.append)
        for line in lines:
            a = _parse_list(line)
            if a and a.filename not in (".", ".."):
                out.append(a)
        return out

    def stat(self, path):
        path = _b(path)
        if self.mlsd:
            try:
                resp = self.ftp.sendcmd("MLST " + path)
                facts = dict(x.split("=", 1) for x in resp.split("\n")[1].strip().split(" ", 1)[0].split(";") if "=" in x)
                isdir = facts.get("type", "").lower() in ("dir", "cdir", "pdir")
                mode = int(facts["unix.mode"], 8) if facts.get("unix.mode") else (0o755 if isdir else 0o644)
                return Attr(path.encode("latin-1"), mode | (st.S_IFDIR if isdir else st.S_IFREG),
                            int(facts.get("size") or 0), _mtime(facts.get("modify", "")))
            except ftplib.error_perm:
                raise FileNotFoundError(2, "파일/폴더가 없습니다")
        cur = self.ftp.pwd()
        try:                                       # 폴더인지 확인: CWD가 되면 폴더
            self.ftp.cwd(path)
            self.ftp.cwd(cur)
            return Attr(path.encode("latin-1"), st.S_IFDIR | 0o755)
        except ftplib.error_perm:
            pass
        try:
            self.ftp.voidcmd("TYPE I")                 # ASCII 모드에서는 SIZE를 거부하는 서버가 많음
            size = self.ftp.size(path) or 0
        except ftplib.error_perm:
            raise FileNotFoundError(2, "파일/폴더가 없습니다")
        mt = 0
        try:
            mt = _mtime(self.ftp.sendcmd("MDTM " + path).split()[-1])
        except ftplib.all_errors:
            pass
        return Attr(path.encode("latin-1"), st.S_IFREG | 0o644, size, mt)

    lstat = stat

    def open(self, path, mode="rb"):
        self.ftp.voidcmd("TYPE I")
        attr = self.stat(path) if "r" in mode else Attr()
        return _File(self.ftp, path, mode, attr)

    def mkdir(self, path):
        self.ftp.mkd(_b(path))

    def rmdir(self, path):
        self.ftp.rmd(_b(path))

    def remove(self, path):
        self.ftp.delete(_b(path))

    def rename(self, a, b):
        self.ftp.rename(_b(a), _b(b))

    def chmod(self, path, mode):
        self.ftp.sendcmd(f"SITE CHMOD {mode & 0o7777:o} {_b(path)}")

    def close(self):
        try:
            self.ftp.quit()
        except Exception:
            self.ftp.close()


class FtpClient:
    """sess["client"] 자리에 들어감: open_sftp()마다 새 FTP 연결(전송마다 연결 하나)."""

    def __init__(self, p):
        self.p = p

    def open_sftp(self):
        return FtpSftp(self.p)

    def exec_command(self, *a, **k):
        raise OSError("FTP 세션에서는 명령을 실행할 수 없습니다 (소유자 변경 등은 SSH/SFTP 세션에서)")

    def close(self):
        pass


def _login(p):
    tls = p.get("tls") == "explicit"
    target = common.check_remote_target(p["host"])
    if tls:
        ctx = ssl.create_default_context()
        if p.get("ftpInsecure") is True:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        ftp = ftplib.FTP_TLS(context=ctx, timeout=15)
    else:
        ftp = ftplib.FTP(timeout=15)
    ftp.encoding = "latin-1"                          # 바이트 경로를 그대로 왕복
    try:
        ftp.connect(target, int(p.get("port") or 21))
        ftp.host = p["host"]                          # TLS SNI·인증서 이름은 입력 호스트로 검증
        ftp.login(p.get("username") or "anonymous", p.get("password") or "")
        if tls:
            ftp.prot_p()                              # 데이터 연결도 암호화
    except ssl.SSLCertVerificationError as e:
        ftp.close()
        raise ValueError("FTPS 서버 인증서를 확인할 수 없습니다(자체 서명·이름 불일치). "
                         "신뢰할 수 있는 서버라면 세션 편집 → '인증서 확인 안 함'을 켜세요(위험).") from e
    except Exception:
        ftp.close()
        raise
    ftp.set_pasv(p.get("passive", True))
    try:
        ftp.sendcmd("OPTS UTF8 ON")
    except ftplib.all_errors:
        pass
    return ftp


async def ftp_handler(ws):
    """FTP 탭: 로그인 확인 후 세션 등록 → 브라우저 SFTP 패널이 /sftp?sid=로 사용."""
    async def send_json(**obj):
        await ws.send(json.dumps(obj, ensure_ascii=False))

    try:
        p = json.loads(await asyncio.wait_for(ws.recv(), 30))
        assert p.get("type") == "connect" and p.get("host")
    except Exception:
        await ws.close(1008, "bad connect message")
        return
    typed = p.get("password")
    filled = dict(p, auth="password")
    vault.fill(filled)
    p["password"] = filled.get("password")
    try:
        f = await asyncio.to_thread(FtpSftp, p)
    except ftplib.error_perm as e:
        code = "auth:target" if str(e).startswith("530") else None
        await send_json(type="error", message=f"FTP 로그인 실패: {e}", code=code)
        await ws.close()
        return
    except Exception as e:
        await send_json(type="error", message=f"FTP 접속 실패: {e}")
        await ws.close()
        return
    await asyncio.to_thread(f.close)
    if p.get("save") and typed and vault.VAULT and common.LOCAL_MODE:
        try:
            vault.VAULT.set(vault.key_of({**p, "port": p.get("port") or 21}), password=typed)
        except vault.Locked:
            pass
    sid = secrets.token_urlsafe(18)
    common.SESSIONS[sid] = {"client": FtpClient(p), "enc": ENCODINGS.get(p.get("encoding"), "utf-8"), "shellpid": None}
    await send_json(type="connected", sid=sid)
    try:
        async for _ in ws:
            pass
    except ConnectionClosed:
        pass
    finally:
        common.SESSIONS.pop(sid, None)
        p.pop("password", None)
