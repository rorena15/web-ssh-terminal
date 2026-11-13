"""11/13 자동 업데이트 잠금(.wst-updating) 시험(Claude 검증). python t_update_lock.py [저장소 루트]
- 죽은 pid가 기록된 잠금은 5초 뒤 만료 → 시작 정리가 지우고 진행
- 살아 있는 pid 잠금은 유지(10분 전) / 형식이 깨진 잠금은 10분 전까지 유지
- 토큰 인수 대상 잠금은 apply_update가 앞 단계에서 실패해도 남지 않음
- launch_ready는 어떤 예외도 밖으로 내보내지 않음
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wst import common, update  # noqa: E402

R = []


def check(name, ok, info=""):
    R.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f" - {info}" if info else ""))


def aged(p, sec):
    t = time.time() - sec
    os.utime(p, (t, t))


tmp = Path(tempfile.mkdtemp(prefix="wst_lock_"))
lock = tmp / ".wst-updating"

# 죽은 pid
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
lock.write_text(json.dumps({"token": "t", "pid": dead.pid}), encoding="utf-8")
aged(lock, 10)
check("죽은 pid 잠금(10초 경과) → 만료", update._lock_expired(lock) is True)
aged(lock, 1)
check("죽은 pid라도 5초 미만이면 유지", update._lock_expired(lock) is False)

# 살아 있는 pid
live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
lock.write_text(json.dumps({"token": "t", "pid": live.pid}), encoding="utf-8")
aged(lock, 60)
check("살아 있는 pid 잠금(1분) → 유지", update._lock_expired(lock) is False)
aged(lock, 700)
check("살아 있는 pid라도 10분 넘으면 만료", update._lock_expired(lock) is True)
live.kill()

# 깨진 형식
lock.write_text("garbage", encoding="utf-8")
aged(lock, 60)
check("형식 깨진 잠금(1분) → 유지", update._lock_expired(lock) is False)
aged(lock, 700)
check("형식 깨진 잠금(10분 초과) → 만료", update._lock_expired(lock) is True)

# 시작 정리: 죽은 pid 잠금이면 30초 기다리지 않고 진행
data = tmp / "data"
data.mkdir()
lock.write_text(json.dumps({"token": "t", "pid": dead.pid}), encoding="utf-8")
aged(lock, 10)
t0 = time.time()
try:
    update.startup_housekeeping(tmp, data)
    ok = True
except Exception as e:  # noqa: BLE001
    ok = False
    print("  ", e)
check("시작 정리: 죽은 주인 잠금 제거 후 바로 진행", ok and not lock.exists() and time.time() - t0 < 5, f"{time.time() - t0:.1f}s")

# apply_update: 토큰 인수 대상 잠금, 앞 단계(staging 없음)에서 실패해도 잠금 제거
lock.write_text(json.dumps({"token": "tok123", "pid": os.getpid()}), encoding="utf-8")
res = update.apply_update(tmp, tmp / "no_staging", data, wait_pid=None, timeout=1, pubkey_b64="A" * 44, lock_token="tok123")
check("apply 앞 단계 실패 → ok:false", res.get("ok") is False, str(res)[:120])
check("apply 실패 후 인수 잠금 남지 않음", not lock.exists())

# launch_ready: 예외를 밖으로 내보내지 않음(FROZEN·키·staging 흉내, 버전 파일 없음)
old = (common.FROZEN, update.UPDATE_PUBKEYS, common.BASE)
upd = tmp / "upd"
(upd / "staging" / "9.9.9").mkdir(parents=True)
os.environ["WST_UPDATE_DIR"] = str(upd)
try:
    common.FROZEN, update.UPDATE_PUBKEYS, common.BASE = True, ("A" * 43 + "=",), tmp
    update.update_dir = lambda: upd
    sys._MEIPASS = str(tmp / "nope")
    try:
        update._stopping = False
        update.launch_ready()
        ok = True
    except BaseException as e:  # noqa: BLE001
        ok = False
        print("  ", type(e).__name__, e)
    check("launch_ready: 버전 파일 없음 등 예외를 밖으로 내보내지 않음", ok)
finally:
    common.FROZEN, update.UPDATE_PUBKEYS, common.BASE = old

print(f"\n{sum(R)}/{len(R)} 통과")
sys.exit(0 if all(R) else 1)
