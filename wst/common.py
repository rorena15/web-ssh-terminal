"""공통: 경로, 실행 모드, 세션 레지스트리, JSON 저장소."""
import json
import os
import sys
import threading
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)   # PyInstaller exe로 실행 중
BASE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent   # exe도 data·logs·certs·static은 옆 폴더 사용
STATIC = BASE / "static"
DATA = Path(os.environ.get("WEBSSH_DATA") or BASE / "data")   # 테스트 때 다른 폴더 지정 가능
KNOWN_HOSTS = DATA / "known_hosts"
DATA.mkdir(exist_ok=True)
if not os.environ.get("WEBSSH_DATA") and (BASE / "known_hosts").exists() and not KNOWN_HOSTS.exists():  # 이전 버전 위치에서 옮김
    (BASE / "known_hosts").replace(KNOWN_HOSTS)

# 서버는 루프백 전용이므로 항상 True → 로컬 터미널·RDP 실행·파일 선택창 등 "이 PC를 조작하는" 기능 허용
LOCAL_MODE = True


def check_remote_target(host):
    """직접 연결 대상을 검사하고 재조회 없이 연결할 IP를 반환. 로컬 모드는 입력 그대로."""
    if LOCAL_MODE:
        return host
    import ipaddress
    import socket
    mine = {"0.0.0.0", "::"}
    try:
        mine |= {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)}
    except OSError:
        pass
    addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    for info in addresses:
        ip = info[4][0]
        a = ipaddress.ip_address(ip.split("%")[0])
        a = getattr(a, "ipv4_mapped", None) or a                     # ::ffff:127.0.0.1 우회 방지
        if a.is_loopback or a.is_unspecified or str(a) in mine or ip in mine:
            raise PermissionError("원격 모드에서는 이 PC 자신으로 직접 연결할 수 없습니다")
    if not addresses:
        raise OSError("대상 주소를 확인할 수 없습니다")
    return addresses[0][4][0]

# 서버 종료 요청 (server.main이 설정)
request_shutdown = None
# 전역 단축키 켜기/끄기 (server.main이 설정, 설정 저장 때 api가 호출)
hotkey_apply = None

# 창 없이 실행할 때 하위 콘솔 프로그램(certutil, wsl 등)의 검은 창이 뜨지 않게
NO_WINDOW = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)

# 터미널 접속마다 발급하는 세션 ID → {"client": SSHClient, "enc": str, "shellpid": int|None}
# (SFTP·모니터링 채널을 같은 SSH 연결에 붙이기 위함)
SESSIONS = {}

_lock = threading.Lock()

DEFAULT_SETTINGS = {
    "autoUpdate": True,         # 종료 시 준비된 업데이트 적용
    "logDir": "",               # 비우면 BASE/logs
    "logDefault": True,         # 새 SSH 세션의 로그 저장 기본값
    "monitor": True,            # 원격 모니터링 바
    "followFolder": True,       # SFTP가 터미널 폴더 따라가기
    "highlight": [
        {"pattern": r"\b(error|errors|fail|failed|failure|fatal|denied|refused|invalid|cannot|unable|critical|panic)\b", "color": "#ff6b6b", "on": True},
        {"pattern": r"\b(warn|warning|warnings|deprecated|timeout|timed out)\b", "color": "#e3b341", "on": True},
        {"pattern": r"\b(ok|success|successful|succeeded|passed|done|enabled|active \(running\))\b", "color": "#56d364", "on": True},
        {"pattern": r"\b(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?\b", "color": "#79c0ff", "on": True},
    ],
}


def _path(name):
    return DATA / f"{name}.json"


def load(name, default):
    try:
        return json.loads(_path(name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:
        # 깨진 파일은 덮어쓰지 않도록 백업 후 기본값
        p = _path(name)
        p.replace(p.with_suffix(".broken.json"))
        return default


def save(name, obj):
    with _lock:
        DATA.mkdir(exist_ok=True)
        tmp = _path(name).with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, _path(name))


def settings():
    s = dict(DEFAULT_SETTINGS)
    s.update(load("settings", {}))
    return s


def log_dir():
    d = settings().get("logDir") or str(BASE / "logs")
    return Path(os.path.expandvars(os.path.expanduser(d)))
