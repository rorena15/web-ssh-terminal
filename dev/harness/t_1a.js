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
const R = {};
const errs = [];
window.addEventListener('error', (e) => errs.push(e.message));
const s1 = await openFake();
// 1) 찾기
typeIn(s1, 'echo alpha error one\r'); typeIn(s1, 'echo beta\r'); typeIn(s1, 'echo alpha two\r');
await until(() => termText(s1).includes('alpha two\n'), 3000, 'echo');
openFind(s1);
const fq = s1.pane.querySelector('.fq'); fq.value = 'alpha'; fq.dispatchEvent(new Event('input'));
R.findCount = s1.pane.querySelector('.fn').textContent;
R.findSel = s1.term.getSelection();
jumpError(s1, 1); R.errSel = s1.term.getSelection();
closeFind(s1);
// 2) 붙여넣기 확인 (여러 줄)
pasteText(s1, 'echo l1\necho l2\n');
await until(() => $('#pasteDlg').open, 2000, 'pasteDlg');
R.pasteInfo = $('#pasteInfo').textContent;
$('#pasteDlg').querySelector('button[value=ok]').click();
await until(() => termText(s1).includes('l2\n'), 3000, 'paste lines');
pasteText(s1, 'rm -rf /tmp/x');
await until(() => $('#pasteDlg').open, 2000, 'pasteDlg2');
R.dangerWarn = $('#pasteWarn').hidden ? 'hidden' : $('#pasteWarn').textContent;
$('#pasteDlg').querySelector('button[value=cancel]').click();
// 3) 탭 이름
s1.customName = 'MYTAB'; refreshTabLabel(s1); R.tabLabel = s1.tab.querySelector('.label').textContent;
// 4) 팔레트
openPalette('분할 4'); await W(100);
R.paletteTop = $('#paletteDlg .pi .pt')?.textContent;
$('#paletteDlg .pq').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
await W(200); R.layoutAfter = layout; setLayout('1');
// 5) MultiExec
const s2 = await openFake();
toggleMultiExec(true); ME.targets = new Set([s1.id, s2.id]); renderMultiBar();
show(s1);
typeIn(s1, 'echo multi\r');
await until(() => termText(s2).includes('multi\n'), 3000, 'multiexec relay');
R.multiRelay = true;
const line = $('#multiBar .me-line'); line.value = 'echo oneline';
line.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
await until(() => termText(s1).includes('oneline\n') && termText(s2).includes('oneline\n'), 3000, 'oneline');
R.multiLine = true;
toggleMultiExec(false);
// 6) 매크로
show(s1); startRecording(); typeIn(s1, 'echo mac\r'); await W(100);
const _p = window.prompt; window.prompt = () => 'M1'; await stopRecording(); window.prompt = _p;
R.macros = (DB.macros || []).map((m) => m.name + ':' + m.steps.length);
show(s2); await playMacro(DB.macros[0], [s2], true);
await until(() => termText(s2).includes('mac\n'), 3000, 'macro play');
R.macroPlay = true;
// 7) SFTP 정렬·필터·드래그 표
setSide('sftp'); await until(() => s2.sftp && s2.sftp.cwd, 5000, 'sftp');
const sp = s2.sftp;
R.sftpCwd = sp.cwd; R.sftpNames = sp.view.map((e) => e.name);
const tok = await sp.call('dlticket', { path: '/home/test/a.txt' });
const resp = await fetch('/dl/' + tok.token + '/a.txt'); R.dl = resp.status + ' ' + (await resp.text()).trim();
// 8) 탭 활동 표시
show(s1); typeIn(s2, 'echo bg\r'); await W(500); R.activity = s2.tab.classList.contains('activity');
R.errors = errs;
return R;
