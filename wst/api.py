"""제어용 WebSocket(/api): 세션 트리·설정 저장, 터널 시작/중지, RDP 실행, 파일 선택창, 로그 폴더 열기.

저장 파일: data/sessions.json  {"folders": [...], "sessions": [...], "tunnels": [...]}
           data/settings.json
비밀번호·키 암호는 저장하지 않는다 (사용할 때마다 브라우저가 물어보고, 탭이 열린 동안만 메모리에 둠).
"""
import asyncio
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import zlib
from contextlib import contextmanager
from pathlib import Path

from websockets.exceptions import ConnectionClosed

from wst import common
from wst import foreground
from wst import localterm
from wst import rawterm
from wst import tools
from wst import vncproxy
from wst import sshconn
from wst import vault
from wst.sshconn import describe
from wst.tunnels import LocalPortError, _target as manager_target, manager

EMPTY = {"folders": [], "sessions": [], "tunnels": []}
MSTSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "mstsc.exe"
_clients = set()


def _broadcast(obj, skip=None):
    msg = json.dumps(obj, ensure_ascii=False)
    for ws in list(_clients):
        if ws is not skip:
            asyncio.ensure_future(_safe_send(ws, msg))


def _vault_changed(ws):
    st = vault.VAULT.status()
    _broadcast({"type": "vault", "vault": st}, skip=ws)
    return {"vault": st}


async def _safe_send(ws, msg):
    try:
        await ws.send(msg)
    except ConnectionClosed:
        pass


def _find(data, kind, sid):
    for x in data.get(kind, []):
        if x.get("id") == sid:
            return x
    if kind == "sessions" and str(sid).startswith("shared:"):          # 공유 세션 파일의 세션
        for x in _shared_sessions().get("shared", []):
            if x["id"] == sid:
                return x
    raise ValueError("저장된 항목을 찾을 수 없습니다 (다른 창에서 삭제됨?)")


def _chain(s, sessions, depth=0):
    """점프 호스트 사슬 (jumpVia = 저장된 SSH 세션을 점프로). 브라우저 core.js jumpChain과 같은 규칙."""
    if s.get("jumpVia"):
        j = next((x for x in sessions if x["id"] == s["jumpVia"]), None)
        if not j or j["id"] == s["id"] or depth > 4:
            return []
        return _chain(j, sessions, depth + 1) + [j]
    return [s["jump"]] if (s.get("jump") or {}).get("host") else []


def ssh_params(s, sec, sessions=None):
    save, hv = sec.get("save") or {}, sec.get("hops") or {}

    def hop(c, v, sv):
        return {"host": c["host"], "port": c.get("port") or 22, "username": c["username"], "auth": c.get("auth", "password"),
                "keyPath": c.get("keyPath"), "password": v.get("password"), "passphrase": v.get("passphrase"), "save": sv,
                "agent": c.get("agent"), "compress": c.get("compress"), "keepalive": c.get("keepalive")}
    if sessions is None:
        sessions = common.load("sessions", EMPTY).get("sessions", []) + _shared_sessions().get("shared", [])
    chain = _chain(s, sessions)
    names = sshconn.hop_names(len(chain))
    if len(chain) == 1 and not hv:                       # 예전 형식(jumpPassword) 호환
        hv = {"jump": {"password": sec.get("jumpPassword"), "passphrase": sec.get("jumpPassphrase")}}
    hops = [hop(c, hv.get(n) or {}, save.get(n)) for c, n in zip(chain, names)]
    p = hop(s, sec, save.get("target"))
    if len(hops) == 1:
        p["jump"] = hops[0]
    elif hops:
        p["jumps"] = hops
    first = chain[0] if chain else s
    proxy = next((x.get("proxy") for x in (s, first) if (x.get("proxy") or {}).get("host")), None)
    if proxy:
        p["proxy"] = proxy
    return p


DETAIL_CMDS = {
    "CPU 상위 프로세스": "ps -eo pid,user,%cpu,%mem,etime,comm --sort=-%cpu 2>/dev/null | head -11 || top -b -n1 | head -20",
    "메모리 상위 프로세스": "ps -eo pid,user,%mem,rss,comm --sort=-%mem 2>/dev/null | head -11",
    "디스크": "df -hP -x tmpfs -x devtmpfs 2>/dev/null || df -h",
    "열린 포트 (LISTEN)": "ss -tulnp 2>/dev/null | head -60 || netstat -tulnp 2>/dev/null | head -60",
    "로그인 사용자 · 가동": "uptime; echo; who",
}


def _remote_detail(client):
    out = {}
    for k, cmd in DETAIL_CMDS.items():
        try:
            o, _ = sshconn.exec_text(client, "export LC_ALL=C; " + cmd, timeout=8)
            out[k] = o.strip() or "(결과 없음)"
        except Exception as e:
            out[k] = f"(실행 실패: {e})"
    return out


def _shared_sessions():
    """설정의 sharedPath(내보낸 JSON 또는 sessions.json)를 읽어 '공유/' 폴더 아래 읽기 전용으로."""
    path = (common.settings().get("sharedPath") or "").strip()
    if not path:
        return {}
    try:
        d = json.loads(Path(os.path.expandvars(path)).read_text(encoding="utf-8-sig"))
        out = []
        for s in d.get("sessions") or []:
            if isinstance(s, dict) and s.get("id") and s.get("type"):
                s = {k: v for k, v in s.items() if k not in ("password", "passphrase", "key")}
                s["id"] = "shared:" + s["id"]
                s["folder"] = "공유" + ("/" + s["folder"] if s.get("folder") else "")
                if s.get("jumpVia"):
                    s["jumpVia"] = "shared:" + s["jumpVia"]
                if s.get("gateway"):
                    s["gateway"] = "shared:" + s["gateway"]
                out.append(s)
        return {"shared": out}
    except Exception as e:
        return {"sharedError": str(e)}


def autostart_tunnels():
    """자동 시작 터널 실행 (블로킹). 저장된 비밀번호/키로만 접속, 처음 보는 호스트 키는 거부."""
    data = common.load("sessions", EMPTY)

    def refuse(host, *_):
        raise ValueError(f"{host} 호스트 키가 저장돼 있지 않아 자동 시작하지 않았습니다 (한 번 직접 접속하세요)")
    for t in data.get("tunnels") or []:
        cur = manager.tunnels.get(t["id"])
        if not t.get("autoStart") or (cur and cur.state in ("on", "starting", "reconnecting")):
            continue
        via = next((s for s in data["sessions"] if s["id"] == t.get("via")), None)
        if not via:
            continue
        try:
            manager.start(t["id"], t, ssh_params(via, {}), refuse)
            print(f"터널 자동 시작: {t.get('name') or t.get('listenPort')}")
        except Exception as e:
            print(f"터널 자동 시작 실패 ({t.get('name') or t.get('listenPort')}): {describe(e)[0]}")


# ── RDP ────────────────────────────────────────────────────
def _validate_rdp_strings(s):
    for key in ("host", "username", "name", "port", "screen"):
        value = s.get(key)
        if isinstance(value, str) and re.search(r'[\x00-\x1f\x7f]', value):
            raise ValueError(f"{key}에 제어문자를 쓸 수 없습니다")


def _mstsc_args(s, address):
    _validate_rdp_strings(s)
    if not re.fullmatch(r'[A-Za-z0-9._\-\[\]:]+', address):
        raise ValueError("RDP 주소 형식이 올바르지 않습니다")
    if not s.get("clipboard", True) or s.get("drives"):
        return [str(MSTSC), str(_rdp_file(s, address))]
    args = [str(MSTSC), f"/v:{address}"]
    if s.get("screen", "full") == "full":
        args.append("/f")
        if s.get("multimon"):
            args.append("/multimon")
    else:
        w, _, h = (s.get("screen") or "1600x900").partition("x")
        args += [f"/w:{int(w)}", f"/h:{int(h)}"]
    if s.get("admin"):
        args.append("/admin")
    return args


def _rdp_file(s, address):
    _validate_rdp_strings(s)
    _validate_rdp_strings({"host": address})
    lines = [f"full address:s:{address}", "prompt for credentials:i:0", "authentication level:i:2",
             f"redirectclipboard:i:{1 if s.get('clipboard', True) else 0}",
             "smart sizing:i:1", "dynamic resolution:i:1", "audiomode:i:0", "autoreconnection enabled:i:1"]
    if s.get("username"):
        lines.append(f"username:s:{s['username']}")
    if s.get("screen", "full") == "full":
        lines.append("screen mode id:i:2")
        lines.append(f"use multimon:i:{1 if s.get('multimon') else 0}")
    else:
        w, _, h = (s.get("screen") or "1600x900").partition("x")
        lines += ["screen mode id:i:1", f"desktopwidth:i:{int(w)}", f"desktopheight:i:{int(h)}"]
    if s.get("drives"):
        lines.append("drivestoredirect:s:*")
    if s.get("admin"):
        lines.append("administrative session:i:1")
    d = common.DATA / "rdp"
    d.mkdir(parents=True, exist_ok=True)
    path = d / (re.sub(r'[\\/:*?"<>|]+', "_", s.get("name") or s["host"]) + ".rdp")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-16", newline="")   # mstsc는 UTF-16 .rdp를 잘 읽음
    return path


_rdp_addrs = {}                       # 세션 id → [주소, 예약 수, 실행 세대, 열린 창 수, 자격 증명 대상, 최신 실행 대상]
_rdp_lock = threading.Lock()


def _rdp_acquire(sid):
    """게이트웨이 경유 RDP용 세션별 루프백 주소(127.77.x.y). Windows 자격 증명이 TERMSRV/주소 단위라
    모두 127.0.0.1로 열면 동시에 연 다른 서버로 앞 서버 비밀번호가 갈 수 있음 → 세션마다 다른 주소."""
    with _rdp_lock:
        if sid in _rdp_addrs:
            _rdp_addrs[sid][1] += 1
            _rdp_addrs[sid][2] += 1
            _rdp_addrs[sid][5] = None
            return _rdp_addrs[sid][0], _rdp_addrs[sid][2]
        used = {e[0] for e in _rdp_addrs.values()}
        h = zlib.crc32(sid.encode()) % (256 * 254)
        while f"127.77.{h // 254}.{h % 254 + 1}" in used:
            h = (h + 1) % (256 * 254)
        _rdp_addrs[sid] = [f"127.77.{h // 254}.{h % 254 + 1}", 1, 1, 0, None, None]
        return _rdp_addrs[sid][0], 1


def _rdp_release(sid):
    """_rdp_lock 안에서 호출. 주소는 터널 정리까지 예약."""
    e = _rdp_addrs.get(sid)
    if not e:
        return False
    e[1] -= 1
    return e[1] == 0


def _launch_rdp(s, data, sec, ask):
    """블로킹. 게이트웨이가 있으면 터널을 열고 mstsc가 끝날 때까지 유지."""
    _validate_rdp_strings(s)
    address = f"{s['host']}:{s.get('port') or 3389}"
    tid = None
    if s.get("gateway"):
        gw = _find(data, "sessions", s["gateway"])
        tid = "rdp-" + s["id"]
        bind, generation = _rdp_acquire(s["id"])
        port = 33890 + zlib.crc32(s["id"].encode()) % 1000          # 세션마다 고정 주소·포트 → mstsc 저장 자격증명 재사용
        cfg = {"type": "local", "bindHost": bind, "listenPort": port, "destHost": s["host"], "destPort": s.get("port") or 3389}

        def check_generation(target):
            entry = _rdp_addrs[s["id"]]
            if entry[2] != generation and entry[5] != target:
                raise ValueError("더 나중에 시작된 RDP 실행의 대상이 다릅니다")

        def start_tunnel():
            params = ssh_params(gw, sec)
            target = manager_target(cfg, params)
            with _rdp_lock:
                if _rdp_addrs[s["id"]][2] == generation:
                    _rdp_addrs[s["id"]][5] = target

            @contextmanager
            def start_guard():
                with _rdp_lock:
                    check_generation(target)
                    yield

            return manager.start(tid, cfg, params, ask, guard=start_guard)

        try:
            try:
                t = start_tunnel()
            except LocalPortError:                                    # 고정 포트 사용 중 → 임의 포트
                cfg["listenPort"] = 0
                t = start_tunnel()
        except Exception:
            with _rdp_lock:
                if _rdp_release(s["id"]):
                    vault.delete_rdp_cred(bind)
                    manager.stop(tid)
                    del _rdp_addrs[s["id"]]
            raise
        address = f"{bind}:{t.port}"
    host_only = address.rsplit(":", 1)[0]
    try:
        saved = vault.VAULT.get(vault.key_of({**s, "port": s.get("port") or 3389}, "rdp:")) if vault.VAULT else {}
        with _rdp_lock:                  # 마지막 창 정리와 새 자격 증명 쓰기를 직렬화
            if tid:
                check_generation(t.target)
                # 대상 교체·중지와 자격 증명 쓰기 사이에 틈을 두지 않음
                with manager.lock:
                    with t.lock:
                        if manager.tunnels.get(tid) is not t or t.stopped:
                            raise ValueError("중지되거나 대상이 바뀐 터널입니다")
                        entry = _rdp_addrs[s["id"]]
                        if not entry[3] or entry[4] != t.target:
                            vault.delete_rdp_cred(host_only)
                        if saved.get("password") and s.get("username"):
                            vault.write_rdp_cred(host_only, s["username"], saved["password"])
                        entry[4] = t.target
                        proc = foreground.open_foreground(lambda: subprocess.Popen(_mstsc_args(s, address)), timeout=20, flash=True)
                        entry[3] += 1
            else:
                if saved.get("password") and s.get("username"):
                    vault.write_rdp_cred(host_only, s["username"], saved["password"])
                proc = foreground.open_foreground(lambda: subprocess.Popen(_mstsc_args(s, address)), timeout=20, flash=True)
    except Exception:
        with _rdp_lock:
            if tid and _rdp_release(s["id"]):
                vault.delete_rdp_cred(host_only)
                manager.stop(tid)
                del _rdp_addrs[s["id"]]
        raise
    if tid:
        def keep():
            proc.wait()
            with _rdp_lock:
                _rdp_addrs[s["id"]][3] -= 1
                if not _rdp_release(s["id"]):      # 같은 세션의 다른 mstsc가 아직 열려 있음
                    return
                entry = _rdp_addrs[s["id"]]
                generation = entry[2]
                if vault.VAULT:
                    vault.delete_rdp_cred(host_only)
            idle = 0
            while idle < 10:                        # mstsc 종료 후 연결이 10초간 없으면 터널 정리
                time.sleep(1)
                with _rdp_lock:
                    if _rdp_addrs.get(s["id"]) is not entry or entry[1] or entry[2] != generation:
                        return                       # 재실행이 이전 정리를 무효화함
                    t = manager.tunnels.get(tid)
                    if not t or t.state == "off":
                        del _rdp_addrs[s["id"]]
                        return
                    idle = idle + 1 if t.conns == 0 else 0
                    if idle == 10:
                        manager.stop(tid)
                        del _rdp_addrs[s["id"]]
        threading.Thread(target=keep, daemon=True).start()
    return address


def _make_shortcut(name, sid):
    if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', sid):
        raise ValueError("세션 id 형식이 올바르지 않습니다")
    desk = Path(os.path.expanduser("~")) / "Desktop"
    try:                                              # OneDrive 등으로 바탕화면 위치가 바뀐 경우
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        desk = Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))
    except OSError:
        pass
    safe = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "세션"
    lnk = desk / f"{safe}.lnk"
    if common.FROZEN:
        target, args = sys.executable, subprocess.list2cmdline(["--session", sid])
    else:
        target = str(Path(sys.executable).with_name("pythonw.exe"))
        args = subprocess.list2cmdline([str(common.BASE / "server.py"), "--open", "--trust", "--auto-exit", "--session", sid])
    icon = Path(sys.executable) if common.FROZEN else common.BASE / "build" / "webssh.ico"
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);$s.TargetPath=$env:TGT;$s.Arguments=$env:ARGS;"
          "$s.WorkingDirectory=$env:WD;$s.IconLocation=$env:ICO;$s.Save()")
    env = dict(os.environ, LNK=str(lnk), TGT=target, ARGS=args, WD=str(common.BASE), ICO=str(icon))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env, check=True,
                   capture_output=True, creationflags=common.NO_WINDOW, timeout=20)
    return str(lnk)


def _pick_folder():
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", 1)
        path = filedialog.askdirectory(parent=root, title="폴더 선택", initialdir=os.path.expanduser("~"))
    finally:
        root.destroy()
    return path.replace("/", "\\") or None


def _version_info():
    """도움말 → 버전 정보: version_info.txt의 FileVersion, 빌드 시각(exe 수정 시각), 실행 환경."""
    import platform
    from importlib import metadata
    try:
        version_file = Path(sys._MEIPASS) / "version_info.txt" if common.FROZEN else common.BASE / "build" / "version_info.txt"
        info = version_file.read_text(encoding="utf-8")
        m = re.search(r"'FileVersion',\s*'([^']+)'", info)
        version = m.group(1) if m else ""
        b = re.search(r"filevers=\(\d+, \d+, \d+, (\d+)\)", info)   # 빌드 번호 (build_exe.py가 올림)
        build = int(b.group(1)) if b else 0
    except OSError:
        version, build = "", 0
    libs = {}
    for name in ("paramiko", "websockets", "cryptography"):
        try:
            libs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:   # exe에는 패키지 메타데이터가 없을 수 있음
            mod = sys.modules.get(name)
            libs[name] = getattr(mod, "__version__", "")
    built = f"build({build})" if common.FROZEN and build else ""
    return {"version": version, "built": built, "frozen": common.FROZEN, "python": platform.python_version(), "libs": libs}


def _pick_file():
    # exe에는 sys.executable -c가 없으므로 호출한 작업 스레드 안에서 Tk를 만들고 정리한다
    import tkinter
    from tkinter import filedialog
    ssh = os.path.expanduser("~/.ssh")
    root = tkinter.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", 1)
        path = filedialog.askopenfilename(parent=root, title="개인키 파일 선택",
                                          initialdir=ssh if os.path.isdir(ssh) else os.path.expanduser("~"))
    finally:
        root.destroy()
    return path.replace("/", "\\") or None


# ── 핸들러 ───────────────────────────────────────────────────
async def api_handler(ws):
    loop = asyncio.get_running_loop()
    pending = {}

    async def send(**obj):
        await ws.send(json.dumps(obj, ensure_ascii=False))

    def ask(host, keytype, fp):
        """스레드에서 호출 → 브라우저에 호스트 키 확인 요청."""
        qid = secrets.token_hex(6)
        fut = loop.create_future()

        async def _ask():
            pending[qid] = fut
            await send(type="hostkey", qid=qid, host=host, keytype=keytype, fingerprint=fp)
            return await fut
        return asyncio.run_coroutine_threadsafe(_ask(), loop).result(timeout=120)

    def on_tunnel(tid, st):
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(
            _safe_send(ws, json.dumps({"type": "tunnel", "id": tid, "status": st}))))

    async def handle(m):
        rid, op = m.get("id"), m.get("op")
        try:
            if op == "load":
                r = {"data": common.load("sessions", EMPTY), "settings": common.settings(),
                     "tunnels": manager.status(), "logDir": str(common.log_dir()),
                     "vault": vault.VAULT.status() if vault.VAULT and common.LOCAL_MODE else None,
                     **await asyncio.to_thread(_shared_sessions),
                     "caps": {"local": common.LOCAL_MODE, "shells": localterm.available() if common.LOCAL_MODE else [],
                              "rdp": common.LOCAL_MODE and MSTSC.exists(),
                              "com": rawterm.list_com_ports() if common.LOCAL_MODE else []}}
            elif op == "saveData":
                for session in m["data"].get("sessions", []):
                    _validate_rdp_strings(session)
                common.save("sessions", m["data"])
                _broadcast({"type": "data", "data": m["data"]}, skip=ws)
                r = {}
            elif op == "saveSettings":
                if not common.LOCAL_MODE:                 # 원격 사용자는 이 PC 경로·전역 단축키 설정을 못 바꿈 (UNC로 NTLM 유출 등)
                    cur = common.settings()
                    for k in ("logDir", "sharedPath", "globalHotkey"):
                        m["settings"].pop(k, None)
                        if k in cur:
                            m["settings"][k] = cur[k]
                common.save("settings", m["settings"])
                if common.hotkey_apply:
                    common.hotkey_apply(bool(m["settings"].get("globalHotkey")))
                _broadcast({"type": "settings", "settings": common.settings()}, skip=ws)
                r = {"logDir": str(common.log_dir())}
            elif op == "tunnelStart":
                data = common.load("sessions", EMPTY)
                cfg = _find(data, "tunnels", m["tid"])
                if cfg.get("type") == "remote" and not common.LOCAL_MODE:
                    raise PermissionError("원격 모드에서는 역방향 터널을 열 수 없습니다 (이 PC의 서비스가 노출됨)")
                via = _find(data, "sessions", cfg["via"])
                t = await asyncio.to_thread(manager.start, m["tid"], cfg, ssh_params(via, m.get("secrets") or {}), ask)
                r = {"status": t.status()}
            elif op == "tunnelStop":
                await asyncio.to_thread(manager.stop, m["tid"])
                r = {}
            elif op == "vncOpen":                     # VNC: 대상에 먼저 연결하고 표 발급 → 브라우저 noVNC가 /vnc?vt=로 이어받음
                data = common.load("sessions", EMPTY)
                s = _find(data, "sessions", m["sid"])
                gw = ssh_params(_find(data, "sessions", s["gateway"]), m.get("secrets") or {}) if s.get("gateway") else None
                r = {"ticket": await asyncio.to_thread(vncproxy.open_target, s["host"], s.get("port") or 5900, gw, ask)}
            elif op == "remoteDetail":                # 모니터링 바 클릭: 상위 프로세스·전체 디스크·열린 포트
                sess = common.SESSIONS.get(m["sid"])
                if not sess:
                    raise ValueError("연결된 SSH 탭이 아닙니다")
                r = {"sections": await asyncio.to_thread(_remote_detail, sess["client"])}
            elif op == "installPubKey":
                sess = common.SESSIONS.get(m["sid"])
                pub = (m.get("pub") or "").strip()
                # 셸 명령에 작은따옴표로 넣으므로 형식을 엄격히 검사 (주석에 ' \ 줄바꿈 금지)
                if not sess or not re.fullmatch(r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+( [\w@.:+-]*)?", pub):
                    raise ValueError("공개키 형식이 올바르지 않거나 탭이 연결되어 있지 않습니다")
                out, code = await asyncio.to_thread(sshconn.exec_sh, sess["client"],
                    "umask 077; mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && "
                    f"(grep -qxF '{pub}' ~/.ssh/authorized_keys || echo '{pub}' >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys")
                if code:
                    raise RuntimeError(f"등록 실패 (종료 코드 {code}): {out.decode(errors='replace')[:200]}")
                r = {}
            elif op == "knownHosts":
                r = {"hosts": await asyncio.to_thread(sshconn.known_hosts)}
            elif op == "forgetHostKey":
                r = {"n": await asyncio.to_thread(sshconn.forget_host_key, m.get("host"), m.get("port") or 22, m.get("name"))}
            elif not common.LOCAL_MODE:
                raise PermissionError("이 기능은 서버가 127.0.0.1로 실행 중일 때만 쓸 수 있습니다")
            elif op == "portScan":                    # 결과는 끝나면 한 번에, 진행률은 scanProgress 메시지
                hosts, ports = tools.parse_hosts(m["hosts"]), tools.parse_ports(m["ports"])

                async def prog(done, total):
                    await send(type="scanProgress", done=done, total=total)
                r = {"open": await tools.scan(hosts, ports, float(m.get("timeout") or 0.8), prog), "hosts": len(hosts), "ports": len(ports)}
            elif op == "listening":
                r = {"ports": await asyncio.to_thread(tools.listening)}
            elif op == "serverStart":
                await asyncio.to_thread(tools.start_server, m["kind"], m["root"], m.get("bind") or "0.0.0.0", m.get("port"), bool(m.get("write")))
                r = {"servers": tools.servers_status(), "ips": tools.local_ips()}
            elif op == "serverStop":
                await asyncio.to_thread(tools.stop_server, m["kind"])
                r = {"servers": tools.servers_status(), "ips": tools.local_ips()}
            elif op == "servers":
                r = {"servers": tools.servers_status(), "ips": tools.local_ips()}
            elif op == "keygen":
                r = await asyncio.to_thread(tools.keygen, m.get("kind") or "ed25519", m.get("bits") or 4096, m.get("comment") or "",
                                            m.get("passphrase") or "", m.get("saveAs") or "")
            elif op == "makeShortcut":                # 바탕화면 바로가기: exe --session <id>
                r = {"path": await asyncio.to_thread(_make_shortcut, m["name"], m["sid"])}
            elif op == "pickFolder":
                r = {"path": await asyncio.to_thread(_pick_folder)}
            elif op == "comPorts":
                r = {"ports": await asyncio.to_thread(rawterm.list_com_ports)}
            elif op == "vaultStatus":
                r = {"vault": vault.VAULT.status() if vault.VAULT else None}
            elif op == "vaultUnlock":
                await asyncio.to_thread(vault.VAULT.unlock, m.get("master") or "")
                r = _vault_changed(ws)
                asyncio.get_running_loop().run_in_executor(None, autostart_tunnels)   # 잠금이 풀리면 대기 중이던 자동 시작 터널
            elif op == "vaultVerify":
                r = {"ok": await asyncio.to_thread(vault.VAULT.verify, m.get("master") or "")}
            elif op == "vaultLock":
                vault.VAULT.lock()
                r = _vault_changed(ws)
            elif op == "vaultMaster":
                await asyncio.to_thread(vault.VAULT.set_master, m.get("old"), m.get("new"))
                r = _vault_changed(ws)
            elif op == "vaultSet":                      # RDP 비밀번호 등 접속과 별개로 저장할 때
                vault.VAULT.set(m["key"], password=m.get("password"))
                r = _vault_changed(ws)
            elif op == "vaultDelete":
                vault.VAULT.delete(m["key"])
                r = _vault_changed(ws)
            elif op == "rdp":
                data = common.load("sessions", EMPTY)
                s = _find(data, "sessions", m["sid"])
                r = {"address": await asyncio.to_thread(_launch_rdp, s, data, m.get("secrets") or {}, ask)}
            elif op == "version":
                r = _version_info()
            elif op == "openLogs":
                d = common.log_dir()
                sub = d / re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", m.get("name") or "").strip(" .")
                target = sub if m.get("name") and sub.is_dir() else d
                target.mkdir(parents=True, exist_ok=True)
                foreground.open_folder(target)
                r = {}
            elif op == "pickFile":
                r = {"path": await asyncio.to_thread(_pick_file)}
            elif op == "shutdown":
                loop.call_later(0.5, common.request_shutdown)
                r = {}
            else:
                raise ValueError(f"unknown op {op}")
            await send(id=rid, ok=True, **r)
        except ConnectionClosed:
            pass
        except Exception as e:
            msg, code = describe(e)
            if msg.startswith("접속 실패: ") and not hasattr(e, "err"):
                msg = str(e)
            await send(id=rid, error=msg, code=code)

    _clients.add(ws)
    manager.listeners.append(on_tunnel)
    try:
        async for msg in ws:
            m = json.loads(msg)
            if m.get("op") == "hostkey_reply":
                f = pending.pop(m.get("qid"), None)
                if f and not f.done():
                    f.set_result(bool(m.get("accept")))
                continue
            asyncio.create_task(handle(m))
    except ConnectionClosed:
        pass
    finally:
        _clients.discard(ws)
        manager.listeners.remove(on_tunnel)
        for f in pending.values():
            if not f.done():
                f.set_result(False)
