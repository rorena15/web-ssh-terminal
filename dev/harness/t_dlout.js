// 끌어 내려받기 시험(11/13 "여러 개 끌다 멈춤"): 화면 행의 실제 pointerdown→dragstart 경로로 받은 DownloadURL을 내려받음.
// lib.js 앞에 붙임. 가짜 sshd(2222) 루트의 /home/test에 f1.bin~f5.bin(각 8MB)이 있어야 함.
// 기대: 같은 행을 다시 끌어도 200(끌기마다 새 일회용 링크), 다섯 개 동시 내려받기 모두 200·8MB, 쓴 링크 재사용은 404.
const R = {};
const SIZE = 8 << 20;
const s = await openFake();
setSide('sftp'); await until(() => s.sftp && s.sftp.cwd, 5000, 'sftp');
const sp = s.sftp;
await sp.list('/home/test', true);
await until(() => sp.view.some((e) => e.name === 'f1.bin'), 5000, 'list');
const rowOf = (n) => sp.el.querySelector(`.sf-row[data-name="${CSS.escape(n)}"]`);
const drag = async (n) => {                       // 끌기 한 번 = pointerdown → (링크 준비) → dragstart
  const row = rowOf(n);
  row.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
  await until(() => row.dlUrl, 3000, 'dlUrl ' + n);
  const dt = new DataTransfer();
  row.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
  const d = dt.getData('DownloadURL');
  if (!d) throw new Error('DownloadURL 없음 ' + n);
  return d.slice(d.indexOf(':', d.indexOf(':') + 1) + 1);
};
const get = async (u) => { const t0 = performance.now(); const r = await fetch(u); const b = await r.arrayBuffer(); return { st: r.status, len: b.byteLength, ms: Math.round(performance.now() - t0) }; };
// 1) 같은 행을 바로 다시 끌기
const u1 = await drag('f1.bin');
R.first = await get(u1);
const u2 = await drag('f1.bin');
R.secondSameRow = await get(u2);
R.newUrlEachDrag = u1 !== u2;
R.reuseUsed = (await get(u1)).st;                 // 이미 쓴 링크 → 404
// 2) 다섯 개를 거의 동시에 끌기
const urls = [];
for (const n of ['f1.bin', 'f2.bin', 'f3.bin', 'f4.bin', 'f5.bin']) urls.push(await drag(n));
const t0 = performance.now();
let ping = null;
const pinger = (async () => { await W(200); const p0 = performance.now(); await fetch('/'); ping = Math.round(performance.now() - p0); })();
R.parallel = await Promise.all(urls.map(get));
await pinger;
R.parallelTotalMs = Math.round(performance.now() - t0);
R.serverPingDuringMs = ping;
R.ok = R.first.st === 200 && R.first.len === SIZE && R.secondSameRow.st === 200 && R.secondSameRow.len === SIZE
  && R.newUrlEachDrag && R.reuseUsed === 404 && R.parallel.every((x) => x.st === 200 && x.len === SIZE);
return R;
