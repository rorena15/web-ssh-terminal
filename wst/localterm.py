"""로컬 터미널 (이 PC의 PowerShell/cmd/WSL) — Windows ConPTY(pywinpty).

보안: 이 기능은 이 PC에서 명령을 실행하므로 서버가 127.0.0.1에만 바인딩된 경우(LOCAL_MODE)에만 허용.
"""
import asyncio
import codecs
import json
import os
import re
import shutil
import subprocess
import threading

from websockets.exceptions import ConnectionClosed

from wst import common

SHELLS = [  # (id, 표시 이름, 실행 파일)
    ("powershell", "PowerShell", "powershell.exe"),
    ("pwsh", "PowerShell 7", "pwsh.exe"),
    ("cmd", "명령 프롬프트", "cmd.exe"),
    ("wsl", "WSL (Linux)", "wsl.exe"),
]


def _wsl_installed():
    """wsl.exe는 배포판이 없어도 있으므로 실제 설치된 배포판이 있는지 확인."""
    try:
        out = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, timeout=5,
                             creationflags=common.NO_WINDOW).stdout
        return bool(out.decode("utf-16-le", "ignore").strip("\x00\r\n﻿ "))
    except Exception:
        return False


_avail = None


def available():
    global _avail
    if _avail is not None:
        return _avail
    if os.name != "nt":
        return []
    try:
        import winpty  # noqa: F401
    except ImportError:
        return []
    _avail = [{"id": i, "name": n} for i, n, exe in SHELLS
              if shutil.which(exe) and (i != "wsl" or _wsl_installed())]
    return _avail


async def local_handler(ws):
    if not common.LOCAL_MODE:
        await ws.close(1008, "local terminal disabled")
        return
    loop = asyncio.get_running_loop()

    async def send_json(**obj):
        await ws.send(json.dumps(obj, ensure_ascii=False))

    try:
        p = json.loads(await asyncio.wait_for(ws.recv(), 30))
        exe = {i: e for i, _, e in SHELLS}[p["shell"]]
        path = shutil.which(exe)
        assert path
    except Exception:
        await ws.close(1008, "bad shell")
        return

    cmd = path
    if p.get("mosh"):                                   # Mosh 세션: WSL의 mosh로 실행
        mo = p["mosh"]
        if not re.fullmatch(r"[\w.\-]+", mo.get("host", "")) or not re.fullmatch(r"[\w.\-]*", mo.get("username", "")):
            await ws.close(1008, "bad mosh target")
            return
        key = os.path.expandvars(os.path.expanduser(mo.get("keyPath") or ""))
        if any(c in key for c in "'\"`$"):
            await ws.close(1008, "bad key path")
            return
        if re.match(r"^[A-Za-z]:\\", key):             # C:\... → /mnt/c/...
            key = "/mnt/" + key[0].lower() + key[2:].replace("\\", "/")
        ssh = f"ssh -p {int(mo.get('port') or 22)}" + (f" -i '{key}'" if key else "")
        cmd = f'"{path}" mosh --ssh="{ssh}" {mo["username"]}@{mo["host"]}' if mo.get("username") else f'"{path}" mosh --ssh="{ssh}" {mo["host"]}'
    from winpty import PtyProcess
    try:
        proc = await asyncio.to_thread(
            PtyProcess.spawn, cmd, cwd=os.path.expanduser("~"),
            dimensions=(int(p.get("rows") or 24), int(p.get("cols") or 80)))
    except Exception as e:
        await send_json(type="error", message=f"실행 실패: {e}")
        await ws.close()
        return

    await send_json(type="connected", sid=None)

    def pump():
        try:
            while True:
                data = proc.read(65536)
                if data:
                    asyncio.run_coroutine_threadsafe(ws.send(data.encode("utf-8")), loop).result()
        except Exception:
            pass

        async def _end():
            try:
                await send_json(type="closed", exit=proc.exitstatus)
                await ws.close()
            except ConnectionClosed:
                pass
        asyncio.run_coroutine_threadsafe(_end(), loop)

    threading.Thread(target=pump, daemon=True).start()

    dec = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        async for msg in ws:
            if isinstance(msg, bytes):
                proc.write(dec.decode(msg))
            else:
                m = json.loads(msg)
                if m.get("type") == "resize":
                    proc.setwinsize(int(m["rows"]), int(m["cols"]))
    except ConnectionClosed:
        pass
    finally:
        try:
            proc.terminate(force=True)
        except Exception:
            pass
