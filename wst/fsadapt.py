"""SFTP가 아닌 파일 시스템을 paramiko SFTPClient처럼 보이게 하는 어댑터 (sftp.py 파일 탐색기 재사용).

- ShellSftp: SFTP 서브시스템이 꺼진 서버 → SSH exec(ls/cat/mkdir…)로 대신 (SCP 모드)
- LocalSftp: 이 PC의 파일 (두 칸 탐색기의 왼쪽 칸, LOCAL_MODE 전용)
경로는 sftp.py 규칙대로 bytes로 들어온다.
"""
import os
import shlex
import stat as st
import time
from pathlib import Path

from wst.ftpconn import Attr


def _s(path):
    return path.decode("utf-8", "surrogateescape") if isinstance(path, bytes) else path


# ── SFTP 없는 서버: 셸 명령으로 ─────────────────────────────
class _ExecFile:
    def __init__(self, client, path, mode, attr):
        self.attr, self.mode = attr, mode
        q = shlex.quote(_s(path))
        self.stdin, self.stdout, self.stderr = client.exec_command(("cat -- " if "r" in mode else "cat > ") + q)
        self.chan = self.stdout.channel

    def prefetch(self, *a):
        pass

    def set_pipelined(self, *a):
        pass

    def stat(self):
        return self.attr

    def read(self, n=-1):
        return self.stdout.read() if n is None or n < 0 else self.stdout.read(n)

    def write(self, data):
        self.stdin.write(data)

    def close(self):
        if "w" in self.mode:
            if not self.chan.closed:
                self.stdin.channel.shutdown_write()
        elif self.chan.closed:
            return
        elif not self.chan.exit_status_ready():           # 다 읽기 전에 닫음(취소) → cat이 끝나길 기다리지 않음
            self.chan.close()
            return
        code = self.chan.recv_exit_status()
        self.chan.close()
        if code:
            raise OSError(f"전송 실패 (종료 코드 {code})")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class ShellSftp:
    def __init__(self, client):
        self.c = client

    def _run(self, cmd):
        _, o, e = self.c.exec_command("sh -c " + shlex.quote(cmd), timeout=20)   # 로그인 셸이 csh/fish여도
        out, err = o.read(), e.read()
        code = o.channel.recv_exit_status()
        if code:
            msg = err.decode("utf-8", "replace").strip()
            if "No such file" in msg:
                raise FileNotFoundError(2, msg)
            if "ermission denied" in msg:
                raise PermissionError(13, msg)
            raise OSError(msg or f"명령 실패 ({code})")
        return out

    def normalize(self, path):
        p = _s(path)
        return self._run("cd -- " + shlex.quote(p if p not in ("", ".") else ".") + " && pwd -P").decode("utf-8", "surrogateescape").strip()

    def _stat_line(self, line):
        # %f=16진 모드 %s=크기 %Y=수정시각 %U %G %n
        f = line.split("\t", 5)
        mode = int(f[0], 16)
        return Attr(f[5].encode("utf-8", "surrogateescape").rsplit(b"/", 1)[-1], mode, int(f[1]), int(f[2]), f[3], f[4])

    def listdir_attr(self, path):
        q = shlex.quote(_s(path))
        out = self._run(f"cd -- {q} && for f in .* *; do [ \"$f\" = . ] || [ \"$f\" = .. ] || [ ! -e \"$f\" -a ! -L \"$f\" ] || "
                        f"stat -c '%f\t%s\t%Y\t%U\t%G\t%n' -- \"$f\"; done 2>/dev/null")
        return [self._stat_line(l) for l in out.decode("utf-8", "surrogateescape").splitlines() if l.count("\t") >= 5]

    def stat(self, path):
        out = self._run("stat -L -c '%f\t%s\t%Y\t%U\t%G\t%n' -- " + shlex.quote(_s(path)))
        return self._stat_line(out.decode("utf-8", "surrogateescape").strip())

    def lstat(self, path):
        out = self._run("stat -c '%f\t%s\t%Y\t%U\t%G\t%n' -- " + shlex.quote(_s(path)))
        return self._stat_line(out.decode("utf-8", "surrogateescape").strip())

    def open(self, path, mode="rb"):
        return _ExecFile(self.c, path, mode, self.stat(path) if "r" in mode else Attr())

    def mkdir(self, path):
        self._run("mkdir -- " + shlex.quote(_s(path)))

    def rmdir(self, path):
        self._run("rmdir -- " + shlex.quote(_s(path)))

    def remove(self, path):
        self._run("rm -f -- " + shlex.quote(_s(path)))

    def rename(self, a, b):
        self._run(f"mv -- {shlex.quote(_s(a))} {shlex.quote(_s(b))}")

    def chmod(self, path, mode):
        self._run(f"chmod {mode & 0o7777:o} -- " + shlex.quote(_s(path)))

    def close(self):
        pass


# ── 이 PC의 파일 ───────────────────────────────────────────
def _local(path):
    """'/C:/Users/x' 또는 '/' (드라이브 목록) 형태의 탐색기 경로 → Windows 경로."""
    p = _s(path).replace("\\", "/")
    if p in ("", ".", "~"):
        p = "/" + str(Path.home()).replace("\\", "/")
    p = p.lstrip("/")
    return p


class _LFile:
    def __init__(self, path, mode):
        self.f = open(path, mode)
        self.attr = _attr(path, os.path.basename(path)) if "r" in mode else Attr()

    def prefetch(self, *a):
        pass

    def set_pipelined(self, *a):
        pass

    def stat(self):
        return self.attr

    def read(self, n=-1):
        return self.f.read(n)

    def write(self, d):
        self.f.write(d)

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


_LINK_TAGS = (0xA000000C, 0xA0000003)          # IO_REPARSE_TAG_SYMLINK, MOUNT_POINT(정션). 클라우드(OneDrive) 등은 일반 파일


def _is_link(s):
    return st.S_ISLNK(s.st_mode) or getattr(s, "st_reparse_tag", 0) in _LINK_TAGS


def _attr(full, name, follow=False):
    s = os.lstat(full)
    if _is_link(s) and not follow:
        return Attr(name.encode("utf-8", "surrogateescape"), st.S_IFLNK | 0o777, 0, int(s.st_mtime))
    if _is_link(s):
        s = os.stat(full)
    mode = (st.S_IFDIR | 0o755) if st.S_ISDIR(s.st_mode) else (st.S_IFREG | (0o644 if os.access(full, os.W_OK) else 0o444))
    return Attr(name.encode("utf-8", "surrogateescape"), mode, s.st_size, int(s.st_mtime))


class LocalSftp:
    """루트(/) = 드라이브 목록, /C:/… = 그 드라이브. 숨김·시스템 파일도 보임."""

    def normalize(self, path):
        p = _local(path)
        if not p:
            return "/"
        if len(p) == 2 and p[1] == ":":
            p += "/"
        return "/" + str(Path(p).resolve()).replace("\\", "/")

    def listdir_attr(self, path):
        p = _local(path)
        if not p:
            import string
            return [Attr(f"{d}:".encode(), st.S_IFDIR | 0o755) for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
        out = []
        with os.scandir(p + ("/" if p.endswith(":") else "")) as it:
            for e in it:
                try:
                    out.append(_attr(e.path, e.name))
                except OSError:
                    pass
        return out

    def stat(self, path):
        p = _local(path)
        if not p:
            return Attr(b"/", st.S_IFDIR | 0o755)
        return _attr(p + ("/" if p.endswith(":") else ""), os.path.basename(p), follow=True)

    def lstat(self, path):
        p = _local(path)
        if not p or p.endswith(":"):
            return self.stat(path)
        return _attr(p, os.path.basename(p))

    def open(self, path, mode="rb"):
        return _LFile(_local(path), mode)

    def mkdir(self, path):
        os.mkdir(_local(path))

    def rmdir(self, path):
        os.rmdir(_local(path))

    def remove(self, path):
        p = _local(path)
        ls = os.lstat(p)
        if _is_link(ls) and getattr(ls, "st_file_attributes", 0) & 0x10:   # 폴더 링크·정션(대상이 없어도): 링크만 제거
            os.rmdir(p)
        else:
            os.remove(p)

    def rename(self, a, b):
        os.rename(_local(a), _local(b))

    def chmod(self, path, mode):
        os.chmod(_local(path), st.S_IWRITE | st.S_IREAD if mode & 0o200 else st.S_IREAD)

    def close(self):
        pass


class LocalClient:
    """sess["client"] 자리: 이 PC 파일."""

    def open_sftp(self):
        return LocalSftp()

    def exec_command(self, *a, **k):
        raise OSError("이 PC 파일 탐색기에서는 명령을 실행할 수 없습니다")

    def close(self):
        pass


async def localfs_handler(ws):
    """이 PC 파일 탭: 세션 등록만 하고 브라우저 SftpPanel이 /sftp?sid=로 사용 (LOCAL_MODE 전용)."""
    import asyncio
    import json
    import secrets

    from websockets.exceptions import ConnectionClosed

    from wst import common
    if not common.LOCAL_MODE:
        await ws.close(1008, "local files disabled")
        return
    try:
        await asyncio.wait_for(ws.recv(), 30)
    except Exception:
        return
    sid = secrets.token_urlsafe(18)
    common.SESSIONS[sid] = {"client": LocalClient(), "enc": "utf-8", "shellpid": None}
    await ws.send(json.dumps({"type": "connected", "sid": sid}))
    try:
        async for _ in ws:
            pass
    except ConnectionClosed:
        pass
    finally:
        from wst.sftp import close_dl
        sess = common.SESSIONS.pop(sid, None)
        if sess is not None:
            await asyncio.to_thread(close_dl, sess)
