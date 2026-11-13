"""11/13 끌어 내려받기 채널 캐시·세션 종료 정리 시험(Claude 검증). python t_dlclose.py [저장소 루트]
- 같은 세션의 내려받기는 채널 하나를 재사용, 동시 요청은 직렬화
- 캐시 채널이 죽으면 한 번 다시 열어 성공
- close_dl: 진행 중 내려받기가 끝난 뒤 채널을 닫고, 그 세션의 남은 표를 지우고, 이후 read_ticket은 None
"""
import sys
import threading
import time
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wst import sftp as S  # noqa: E402

R = []


def check(name, ok, info=""):
    R.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f" - {info}" if info else ""))


class F:
    def __init__(self, ch, data):
        self.ch, self.data = ch, data

    def prefetch(self):
        pass

    def read(self):
        with self.ch.lock:
            self.ch.active += 1
            self.ch.peak = max(self.ch.peak, self.ch.active)
        time.sleep(self.ch.delay)
        with self.ch.lock:
            self.ch.active -= 1
        if self.ch.dead:
            raise EOFError("Channel closed.")
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class St:
    st_size = 5


class Chan:
    def __init__(self, delay):
        self.closed, self.dead, self.delay = False, False, delay
        self.lock, self.active, self.peak = threading.Lock(), 0, 0
        self.closed_at = None

    def stat(self, p):
        if self.closed:
            raise EOFError("closed")
        return St()

    def open(self, p, mode):
        return F(self, b"hello")

    def close(self):
        self.closed = True
        self.closed_at = time.time()


class Client:
    def __init__(self, delay=0.0):
        self.opened, self.delay = [], delay

    def open_sftp(self):
        c = Chan(self.delay)
        self.opened.append(c)
        return c


# 1) 재사용·직렬화
cl = Client(delay=0.2)
sess = {"client": cl}
toks = [S.make_ticket(sess, b"/f", "f.txt") for _ in range(4)]
out = []
ths = [threading.Thread(target=lambda t=t: out.append(S.read_ticket(t))) for t in toks]
[t.start() for t in ths]
[t.join() for t in ths]
check("동시 4건 모두 성공", len(out) == 4 and all(o == ("f.txt", b"hello") for o in out), str(out[:1]))
check("채널 하나만 엶", len(cl.opened) == 1, f"opened={len(cl.opened)}")
check("읽기 직렬화(동시 1개)", cl.opened[0].peak == 1, f"peak={cl.opened[0].peak}")

# 2) 죽은 캐시 채널 → 재시도 성공
cl.opened[0].dead = True
cl.opened[0].delay = 0
r = S.read_ticket(S.make_ticket(sess, b"/f", "f.txt"))
check("죽은 채널 뒤 재시도 성공", r == ("f.txt", b"hello") and len(cl.opened) == 2 and cl.opened[0].closed,
      f"r={r}, opened={len(cl.opened)}")

# 3) close_dl: 진행 중 내려받기 뒤 닫힘, 남은 표 삭제, 이후 None
cl2 = Client(delay=0.5)
s2 = {"client": cl2}
other = {"client": Client()}
busy = S.make_ticket(s2, b"/f", "a")
left = S.make_ticket(s2, b"/f", "b")
keep = S.make_ticket(other, b"/f", "c")
res = {}
t = threading.Thread(target=lambda: res.setdefault("r", S.read_ticket(busy)))
t.start()
time.sleep(0.15)                      # 읽기 진행 중
t0 = time.time()
S.close_dl(s2)
t.join()
ch = cl2.opened[0]
check("진행 중 내려받기 정상 완료", res.get("r") == ("a", b"hello"), str(res.get("r")))
check("close_dl은 읽기가 끝난 뒤 채널을 닫음", ch.closed and time.time() - t0 >= 0.3, f"waited={time.time() - t0:.2f}s")
check("그 세션의 남은 표 삭제", left not in S.DL_TICKETS)
check("다른 세션 표는 유지", keep in S.DL_TICKETS)
check("dl_sftp 캐시 제거", "dl_sftp" not in s2)
late = S.make_ticket(s2, b"/f", "late")
check("종료 후 read_ticket → None, 새 채널 안 엶", S.read_ticket(late) is None and len(cl2.opened) == 1,
      f"opened={len(cl2.opened)}")
S.DL_TICKETS.clear()

print(f"\n{sum(R)}/{len(R)} 통과")
sys.exit(0 if all(R) else 1)
