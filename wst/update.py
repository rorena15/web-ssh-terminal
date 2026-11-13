"""서명된 릴리즈 준비와 종료 후 교체. 사용자 데이터는 교체하지 않는다."""
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from wst import common

REPO = "rorena15/web-ssh-terminal"
UPDATE_PUBKEY = ""  # 키 생성 후 공개키(base64 32바이트)를 채운다.
MANAGED = ("W.S.T.exe", "_internal", "static", "LICENSE", "README.md", "README.ko.md", "SECURITY.md")
_copy = shutil.copy2
_guard = threading.Lock()
_status = {}
_last_result = None
_stopping = False


class UpdateError(Exception):
    pass


def parse_version(s) -> tuple[int, int, int]:
    if not isinstance(s, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", s):
        raise UpdateError("잘못된 버전")
    try:
        return tuple(map(int, s.split(".")))
    except ValueError as e:
        raise UpdateError("잘못된 버전") from e


def check_path(p: str) -> None:
    if not isinstance(p, str) or not p or any(c in p for c in "\\:\0"):
        raise UpdateError("잘못된 경로")
    parts = p.split("/")
    for part in parts:
        if (part in ("", ".", "..") or part.endswith((" ", "."))
                or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I)
                or any(ord(c) < 32 or c in '<>"|?*' for c in part)):
            raise UpdateError("허용하지 않는 경로")
    if parts[0] not in MANAGED or (len(parts) > 1 and parts[0] not in ("_internal", "static")):
        raise UpdateError("관리 대상 밖 경로")


def _key(value=None):
    return value if value is not None else (os.environ.get("WST_UPDATE_PUBKEY", UPDATE_PUBKEY) if not common.FROZEN else UPDATE_PUBKEY)


def verify_manifest(manifest_bytes: bytes, sig: bytes, current_version: str, pubkey_b64: str | None = None) -> dict:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(_key(pubkey_b64), validate=True)).verify(sig, manifest_bytes)
        m = json.loads(manifest_bytes)
        if type(m["format"]) is not int or m["format"] != 1 or parse_version(m["version"]) <= parse_version(current_version):
            raise UpdateError("형식 또는 버전 거부")
        z = m["zip"]
        if type(z["size"]) is not int or not 0 <= z["size"] <= 1 << 30:
            raise UpdateError("잘못된 zip 크기")
        _digest(z["sha256"])
        seen, total = set(), 0
        for f in m["files"]:
            check_path(f["path"])
            p = f["path"].casefold()
            if p in seen or any(p.startswith(x + "/") or x.startswith(p + "/") for x in seen):
                raise UpdateError("중복 또는 충돌 경로")
            seen.add(p)
            for k in ("size", "compress_size", "data_offset"):
                if type(f[k]) is not int or f[k] < 0:
                    raise UpdateError("잘못된 크기/오프셋")
            if type(f["method"]) is not int or f["method"] not in (0, 8) or f["data_offset"] + f["compress_size"] > z["size"]:
                raise UpdateError("압축 구간 거부")
            _digest(f["sha256"])
            total += f["size"]
        if "w.s.t.exe" not in seen or total > 1 << 30:
            raise UpdateError("exe 누락 또는 크기 초과")
        return m
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError("manifest 검증 실패") from e


def _digest(s):
    if not isinstance(s, str) or not re.fullmatch("[0-9a-fA-F]{64}", s):
        raise UpdateError("잘못된 SHA-256")


def _safe(root, p):
    check_path(p)
    root = Path(root).absolute()
    _no_links(root)
    root = root.resolve()
    dest = root.joinpath(*p.split("/"))
    for part in (dest, *dest.parents):
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise UpdateError("링크 경로 거부")
    if root not in dest.resolve().parents:
        raise UpdateError("경로 이탈")
    return dest


def _no_links(p):
    for part in (p, *p.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise UpdateError("링크 경로 거부")


def _hash(p):
    with p.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def local_hashes(base: Path) -> dict[str, str]:
    base = base.absolute()
    result = {}
    for name in MANAGED:
        top = _safe(base, name)
        paths = top.rglob("*") if top.is_dir() else [top]
        for p in paths:
            rel = p.relative_to(base).as_posix()
            p = _safe(base, rel)
            if p.is_file():
                result[rel] = _hash(p)
    return result


def plan(manifest: dict, base: Path) -> list[dict]:
    hashes = local_hashes(base)
    return [f for f in manifest["files"] if hashes.get(f["path"]) != f["sha256"].lower()]


def _verify_tree(root, m, exact=False):
    for f in m["files"]:
        p = _safe(root, f["path"])
        if not p.is_file() or p.stat().st_size != f["size"] or _hash(p) != f["sha256"].lower():
            raise UpdateError("파일 검증 실패: " + f["path"])
    if exact and set(local_hashes(root)) != {f["path"] for f in m["files"]}:
        raise UpdateError("예상 밖 관리 파일")


def _request(url, limit, version, opener=None, headers=None):
    if urlsplit(url).scheme != "https" and not (not common.FROZEN and opener is not None and urlsplit(url).scheme == "http"):
        raise UpdateError("HTTPS만 허용")
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            if urlsplit(newurl).scheme != "https":
                raise UpdateError("HTTPS 리디렉션만 허용")
            return super().redirect_request(req, fp, code, msg, hdrs, newurl)
    client = opener or urllib.request.build_opener(Redirect())
    req = urllib.request.Request(url, headers={"User-Agent": "W.S.T-updater/" + version, **(headers or {})})
    try:
        response = client.open(req, timeout=30) if hasattr(client, "open") else client(req, timeout=30)
    except urllib.error.HTTPError as e:
        if not headers:
            raise
        e.close()
        return e.code, b""
    with response as r:
        code = r.status if hasattr(r, "status") else r.getcode()
        if headers and code != 206:
            return code, b""
        data = r.read(limit + 1)
        if len(data) > limit:
            raise UpdateError("응답 크기 초과")
        return code, data


def _write_json(p, value):
    _no_links(p.absolute())
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    _no_links(tmp.absolute())
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _read_json(p, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _remove(p):
    _no_links(p.absolute())
    if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
        raise UpdateError("정리 대상 링크 거부")
    if p.is_dir():
        # 링크를 따라 사용자 파일을 지우지 않는다.
        for child in p.rglob("*"):
            if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                raise UpdateError("정리 대상 링크 거부")
        shutil.rmtree(p)
    else:
        p.unlink(missing_ok=True)


def _ready(staging, current_version, pubkey_b64=None):
    _no_links(staging.absolute())
    marker = staging / ".ready"
    if marker.is_symlink():
        raise UpdateError("ready 링크 거부")
    saved = _read_json(marker)
    if not saved:
        raise UpdateError("준비 정보 없음")
    raw = base64.b64decode(saved["manifest"], validate=True)
    sig = base64.b64decode(saved["sig"], validate=True)
    m = verify_manifest(raw, sig, current_version, pubkey_b64)
    _verify_tree(staging, m, exact=True)
    return m


def prepare(manifest_bytes, sig, zip_url: str, base: Path, upd_dir: Path, current_version: str, pubkey_b64=None, opener=None) -> Path:
    m = verify_manifest(manifest_bytes, sig, current_version, pubkey_b64)
    staging = upd_dir / "staging" / m["version"]
    try:
        _no_links(staging.absolute())
        try:
            with tempfile.TemporaryFile(dir=base):
                pass
        except OSError as e:
            raise UpdateError("이 위치에서는 자동 업데이트를 할 수 없습니다") from e
        if (_read_json(upd_dir / "failures.json", {}).get(m["version"], 0)) >= 3:
            raise UpdateError("이 버전 적용 3회 실패")
        if (staging / ".ready").exists():
            _ready(staging, current_version, pubkey_b64)
            return staging
        _remove(staging)
        staging.mkdir(parents=True)
        for old in staging.parent.iterdir():
            if old != staging:
                try:
                    parse_version(old.name)
                except UpdateError:
                    try:
                        _log(common.DATA, "버전 이름이 아닌 staging 항목을 건너뜁니다: " + old.name)
                    except OSError:
                        pass
                    continue
                _remove(old)
        needed = plan(m, base)
        full = not _safe(base, "W.S.T.exe").is_file() or sum(f["compress_size"] for f in needed) > m["zip"]["size"] / 2
        for f in needed if not full else []:
            n, start = f["compress_size"], f["data_offset"]
            if n:
                code, packed = _request(zip_url, n, current_version, opener, {"Range": f"bytes={start}-{start+n-1}"})
                if code != 206:
                    full = True
                    break
                if len(packed) != n:
                    raise UpdateError("Range 길이 불일치")
            else:
                packed = b""
            if f["method"] == 8:
                dec = zlib.decompressobj(-15)
                data = dec.decompress(packed, f["size"] + 1)
                if len(data) > f["size"] or dec.unconsumed_tail or not dec.eof or dec.unused_data:
                    raise UpdateError("압축 해제 크기/스트림 거부")
            else:
                data = packed
            _put(staging, f, data)
        if full:
            download = upd_dir / "download"
            _no_links(download.absolute())
            download.mkdir(parents=True, exist_ok=True)
            archive = download / "release.zip"
            _no_links(archive.absolute())
            _, data = _request(zip_url, m["zip"]["size"], current_version, opener)
            if len(data) != m["zip"]["size"] or hashlib.sha256(data).hexdigest() != m["zip"]["sha256"].lower():
                raise UpdateError("zip 검증 실패")
            archive.write_bytes(data)
            try:
                with zipfile.ZipFile(archive) as z:
                    for f in m["files"]:
                        info = z.getinfo("W.S.T/" + f["path"])
                        if info.file_size != f["size"] or info.compress_size != f["compress_size"] or info.compress_type != f["method"]:
                            raise UpdateError("zip 항목 불일치")
                        with z.open(info) as stream:
                            _put(staging, f, stream.read(f["size"] + 1))
            finally:
                archive.unlink(missing_ok=True)
        else:
            for f in m["files"]:
                if f not in needed:
                    dest = _safe(staging, f["path"])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(_safe(base, f["path"]), dest)
        _verify_tree(staging, m, exact=True)
        _write_json(staging / ".ready", {"manifest": base64.b64encode(manifest_bytes).decode(), "sig": base64.b64encode(sig).decode()})
        return staging
    except Exception as e:
        _remove(staging)
        raise UpdateError(str(e)) from e


def _put(root, f, data):
    if len(data) != f["size"] or hashlib.sha256(data).hexdigest() != f["sha256"].lower():
        raise UpdateError("받은 파일 검증 실패")
    p = _safe(root, f["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def current_version(base=None):
    try:
        p = Path(sys._MEIPASS) / "version_info.txt" if common.FROZEN and base is None else Path(base or common.BASE) / "build/version_info.txt"
        if base is not None and (Path(base) / "_internal/version_info.txt").exists():
            p = Path(base) / "_internal/version_info.txt"
        version = re.search(r"'FileVersion',\s*'([^']+)'", p.read_text(encoding="utf-8")).group(1)
        parse_version(version)
        return version
    except (OSError, UnicodeError, AttributeError, UpdateError) as e:
        raise UpdateError("현재 버전을 읽을 수 없습니다") from e


def _wait_pid(pid, timeout):
    if not pid:
        return
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return
            raise UpdateError("프로세스 대기 권한 없음")
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise UpdateError("프로세스 종료 대기 시간 초과")
        finally:
            kernel.CloseHandle(handle)
    else:
        end = time.monotonic() + timeout
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() >= end:
                raise UpdateError("프로세스 종료 대기 시간 초과")
            time.sleep(0.1)


def _lock_expired(lock):
    if not lock.exists():
        return False
    age = time.time() - lock.stat().st_mtime
    saved = _read_json(lock)
    if (not isinstance(saved, dict) or not isinstance(saved.get("token"), str)
            or not saved["token"] or type(saved.get("pid")) is not int or saved["pid"] <= 0):
        return age > 600
    if age > 600:
        return True
    if age < 5:
        return False
    pid = saved["pid"]
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 87
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass
    return False


def apply_update(target: Path, staging: Path, data_dir: Path, wait_pid: int | None = None, timeout: float = 60, pubkey_b64=None, lock_token=None) -> dict:
    lock, backup = target / ".wst-updating", target / ".wst-backup"
    owned, moved, installed, m = False, [], set(), None
    try:
        _no_links(target.absolute())
        _no_links(lock.absolute())
        _no_links(backup.absolute())
        saved = _read_json(lock)
        if lock_token is not None and isinstance(saved, dict) and saved.get("token") == lock_token:
            owned = True
            _write_json(lock, {"token": lock_token, "pid": os.getpid()})
            _wait_pid(wait_pid, timeout)
        else:
            _wait_pid(wait_pid, timeout)
            if _lock_expired(lock):
                lock.unlink()
            with lock.open("x", encoding="utf-8") as f:
                owned = True
                json.dump({"token": secrets.token_hex(32), "pid": os.getpid()}, f)
        previous = current_version(target)
        m = _ready(staging, previous, pubkey_b64)
        failures_path = staging.parent.parent / "failures.json"
        if _read_json(failures_path, {}).get(m["version"], 0) >= 3:
            raise UpdateError("이 버전 적용 3회 실패")
        if backup.exists():
            raise UpdateError("이전 백업이 남아 있음")
        # 원본 트리 링크/경로를 이동 전에 모두 검사한다.
        local_hashes(target)
        backup.mkdir()
        for name in MANAGED:
            src = _safe(target, name)
            if src.exists():
                src.rename(_safe(backup, name))
                moved.append(name)
        for f in m["files"]:
            dest = _safe(target, f["path"])
            installed.add(f["path"].split("/")[0])
            dest.parent.mkdir(parents=True, exist_ok=True)
            _copy(_safe(staging, f["path"]), dest)
        _verify_tree(target, m, exact=True)
        result = {"ok": True, "from": previous, "to": m["version"], "notes_url": m.get("notes_url", ""), "at": time.time()}
        _write_json(data_dir / "update_result.json", result)
        lock.unlink()
        owned = False
    except Exception as e:
        errors = [str(e)]
        for name in installed:
            try:
                _remove(_safe(target, name))
            except Exception as rollback:
                errors.append("복사본 정리 실패: " + str(rollback))
        for name in reversed(moved):
            try:
                _safe(backup, name).rename(_safe(target, name))
            except Exception as rollback:
                errors.append("백업 복구 실패: " + str(rollback))
        try:
            if owned and backup.exists() and not any(backup.iterdir()):
                backup.rmdir()
        except OSError as cleanup:
            errors.append("빈 백업 정리 실패: " + str(cleanup))
        result = {"ok": False, "error": "; ".join(errors)}
        if m is not None:
            try:
                counts = _read_json(failures_path, {})
                counts[m["version"]] = counts.get(m["version"], 0) + 1
                _write_json(failures_path, counts)
            except Exception as record:
                result["error"] += "; 실패 횟수 기록 실패: " + str(record)
        try:
            _log(data_dir, result["error"])
        except OSError:
            pass
        try:
            _write_json(data_dir / "update_result.json", result)
        except Exception as record:
            result["error"] += "; 결과 기록 실패: " + str(record)
    finally:
        try:
            _no_links(lock.absolute())
            saved = _read_json(lock)
            if owned or (lock_token is not None and isinstance(saved, dict) and saved.get("token") == lock_token):
                lock.unlink(missing_ok=True)
        except Exception as unlock:
            result["error"] = result.get("error", "") + "; 잠금 해제 실패: " + str(unlock)
    return result


def _log(data_dir, error):
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "server.log").open("a", encoding="utf-8") as f:
        f.write("update: " + str(error).replace("\n", " ").replace("\r", " ") + "\n")


def check_once(base: Path, data_dir: Path, upd_dir: Path, current_version: str, latest_url=None, pubkey_b64=None, opener=None) -> dict:
    try:
        if not common.FROZEN or not _read_json(data_dir / "settings.json", {}).get("autoUpdate", True):
            result = {"state": "disabled", "version": current_version}
            return result
        parse_version(current_version)
        if not _key(pubkey_b64):
            result = {"state": "disabled", "version": current_version, "error": "업데이트 공개키 미설정"}
            return result
        url = latest_url or (os.environ.get("WST_UPDATE_URL") if not common.FROZEN else None) or f"https://api.github.com/repos/{REPO}/releases/latest"
        _, raw = _request(url, 1 << 20, current_version, opener)
        release = json.loads(raw)
        assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
        _, raw = _request(assets["manifest.json"], 1 << 20, current_version, opener)
        _, sig = _request(assets["manifest.json.sig"], 1 << 20, current_version, opener)
        # 같은/이전 버전도 서명과 구조를 확인한 뒤 최신으로 표시한다.
        m = verify_manifest(raw, sig, "0.0.0", pubkey_b64)
        if parse_version(m["version"]) <= parse_version(current_version):
            result = {"state": "latest", "version": current_version}
            return result
        staging = prepare(raw, sig, assets[m["zip"]["name"]], base, upd_dir, current_version, pubkey_b64, opener)
        result = {"state": "ready", "version": m["version"], "staging": str(staging)}
        return result
    except Exception as e:
        result = {"state": "error", "version": current_version, "error": str(e)}
        try:
            _log(data_dir, e)
        except OSError:
            pass
        return result
    finally:
        result["last_check"] = time.time()
        try:
            _write_json(data_dir / "update_state.json", result)
        except Exception as e:
            try:
                _log(data_dir, "업데이트 상태 저장 실패: " + str(e))
            except OSError:
                pass


def startup_housekeeping(base: Path, data_dir: Path) -> dict | None:
    def log(error):
        try:
            _log(data_dir, error)
        except Exception:
            pass

    lock = base / ".wst-updating"
    timed_out = False
    try:
        _no_links(lock.absolute())
        end = time.monotonic() + 30
        while lock.exists():
            if _lock_expired(lock):
                lock.unlink()
                break
            if time.monotonic() >= end:
                timed_out = True
                break
            time.sleep(0.2)
    except Exception as e:
        log(e)
    if timed_out:
        raise UpdateError("업데이트 적용 중입니다. 잠시 뒤 다시 실행하세요")
    p = data_dir / "update_result.json"
    result = None
    try:
        if p.exists():
            result = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log(e)
    backup = base / ".wst-backup"
    try:
        _no_links(backup.absolute().parent)
        if isinstance(result, dict) and result.get("ok") is True:
            _remove(backup)
        elif backup.exists():
            log("업데이트 성공 결과가 명시되지 않아 백업을 보존합니다")
    except Exception as e:
        log(e)
    if isinstance(result, dict) and result.get("ok") is True:
        try:
            parse_version(result.get("to"))
            _remove(update_dir() / "staging" / result["to"])
        except Exception as e:
            log(e)
    try:
        p.unlink(missing_ok=True)
    except Exception as e:
        log(e)
    return result


def update_dir():
    override = os.environ.get("WST_UPDATE_DIR") if not common.FROZEN else None
    return Path(override or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "W.S.T/update")


def status(consume=True):
    global _last_result
    if not common.FROZEN:
        s = {"state": "disabled", "error": "exe에서만 지원", "current_version": "-", "checking": _guard.locked()}
        try:
            s["current_version"] = current_version()
        except Exception:
            pass
        if consume and _last_result:
            s["last_result"], _last_result = _last_result, None
        return s
    s = dict(_status or common.load("update_state", {}))
    if common.FROZEN and not _key():
        s.update(state="disabled", error="업데이트 공개키 미설정")
    try:
        s["current_version"] = current_version()
    except UpdateError:
        s["current_version"] = "-"
    if s["current_version"] != "-" and s.get("state") == "ready" and parse_version(s["version"]) <= parse_version(s["current_version"]):
        s.update(state="latest", version=s["current_version"])
    backup = common.BASE / ".wst-backup"
    if backup.exists() or backup.is_symlink():
        s.update(state="error", error=f"이전 업데이트 백업이 남아 있어 자동 업데이트를 멈췄습니다({backup} 확인)")
    s["checking"] = _guard.locked()
    if consume and _last_result:
        s["last_result"], _last_result = _last_result, None
    return s


def start_check():
    if not common.FROZEN:
        return status(consume=False)
    if _stopping or not _guard.acquire(False):
        return status(consume=False)
    def run():
        global _status
        try:
            _status = check_once(common.BASE, common.DATA, update_dir(), current_version())
        except UpdateError as e:
            _status = {"state": "error", "error": str(e)}
            _log(common.DATA, e)
        finally:
            _guard.release()
    threading.Thread(target=run, daemon=True).start()
    return status(consume=False)


async def schedule():
    import asyncio
    await asyncio.sleep(60)
    while True:
        last = _read_json(common.DATA / "update_state.json", {}).get("last_check", 0)
        if time.time() - last >= 86400:
            start_check()
        await asyncio.sleep(60)


def launch_ready():
    global _stopping
    _stopping = True

    def log(error):
        try:
            _log(common.DATA, error)
        except Exception:
            pass

    try:
        if not common.FROZEN or not _key() or _guard.locked():
            return
        root = update_dir() / "staging"
        if not root.exists():
            return
        version = current_version()
        candidates = []
        for staging in root.iterdir():
            try:
                key = parse_version(staging.name)
            except UpdateError:
                continue
            if staging.is_dir():
                candidates.append((key, staging))
        for _, staging in sorted(candidates, key=lambda item: item[0], reverse=True):
            try:
                m = _ready(staging, version)
                if _read_json(update_dir() / "failures.json", {}).get(m["version"], 0) >= 3:
                    continue
                exe = _safe(staging, "W.S.T.exe")
                lock = common.BASE / ".wst-updating"
                _no_links(lock.absolute())
                if _lock_expired(lock):
                    lock.unlink()
                token = secrets.token_hex(32)
                with lock.open("x", encoding="utf-8") as f:
                    json.dump({"token": token, "pid": os.getpid()}, f)
                try:
                    child = subprocess.Popen([str(exe), "--apply-update", "--target", str(common.BASE), "--wait-pid", str(os.getpid()), "--staging", str(staging), "--lock-token", token],
                                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | common.NO_WINDOW, close_fds=True)
                    _write_json(lock, {"token": token, "pid": child.pid})
                except Exception:
                    lock.unlink(missing_ok=True)
                    raise
                return
            except Exception as e:
                log(e)
    except Exception as e:
        log(e)
