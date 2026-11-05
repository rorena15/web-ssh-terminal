// 테스트 공통: 각 테스트 스크립트 앞에 붙임
const W = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(f, ms = 8000, what = '') {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { const v = f(); if (v) return v; } catch {} await W(50); }
  throw new Error('timeout: ' + what + ' ' + f.toString().slice(0, 120));
}
// 호스트 키·비밀번호 창 자동 응답
function autoAnswer(pw = 'pw') {
  if (window.__auto) return;
  window.__auto = setInterval(() => {
    const hk = document.querySelector('#hostkeyDlg');
    if (hk.open) hk.querySelector('button[value=yes]').click();
    const sd = document.querySelector('#secretDlg');
    if (sd.open && !sd.__done) {
      sd.__done = true;
      setTimeout(() => {
        sd.querySelectorAll('#secFields input').forEach((i) => { i.value = pw; });
        sd.querySelector('button[value=ok]').click();
        sd.__done = false;
      }, 30);
    }
  }, 50);
}
function quick(target) {
  const q = document.querySelector('#quick');
  q.value = target;
  q.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
}
const termText = (s) => { const b = s.term.buffer.active; let o = []; for (let y = 0; y < b.length; y++) o.push(b.getLine(y).translateToString(true)); return o.join('\n'); };
const typeIn = (s, txt) => s.term.input ? s.term.input(txt) : sendInput(s, new TextEncoder().encode(txt));
async function openFake(port = 2222) {
  autoAnswer();
  const n = tabs.length;
  quick(`test@127.0.0.1:${port}`);
  await until(() => tabs.length > n, 3000, 'tab');
  const s = tabs[tabs.length - 1];
  await until(() => s.state === 'on', 10000, 'connect');
  await until(() => termText(s).includes('$ '), 5000, 'prompt');
  return s;
}
const s1 = await openFake();
typeIn(s1, 'echo error here\r');
await until(() => termText(s1).includes('error here\n'), 3000, 'echo');
await W(300);
const hl = s1.hl.groups.filter(g=>!g.marker.isDisposed).length;
await until(() => s1.mon && s1.mon.mem, 6000, 'monitor');
const s2 = await openFake();
await W(4000);
const before = s1.mon;  // s1 hidden now: mon should stop updating
const t1 = JSON.stringify(s1.mon); await W(4000); const stale = JSON.stringify(s1.mon) === t1;
return { hlGroups: hl, monS1: !!before, s1MonitorStopped: stale, s2mon: !!s2.mon, tabs: tabs.length, status: document.querySelector('#sbText').textContent.slice(0,120) };
