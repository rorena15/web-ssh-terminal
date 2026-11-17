// 11/17 메뉴 개편: 기능 끔 시 메뉴 숨김·부모 숨김, 메뉴가 열린 동안 키가 터미널로 새지 않음, 닫으면 포커스 복귀 (Claude 작성)
// lib.js 앞에 붙임. 가짜 sshd 2222 필요.
const O = { errors: [] };
const vis = (b) => { const r = b.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(b).display !== 'none'; };
const shown = () => [...document.querySelectorAll('.ctx:not([hidden]) button')].filter(vis).map((b) => b.childNodes[0]?.textContent.trim());
const openBar = async (k) => { hideMenu(); document.querySelector(`#menubar [data-menu=${k}]`).click(); await W(150); };
const hover = async (label) => { const b = [...document.querySelectorAll('.ctx button')].find((x) => vis(x) && x.textContent.startsWith(label)); if (!b) return false; b.dispatchEvent(new MouseEvent('mouseenter')); await W(150); return true; };
const saved = SETTINGS.hiddenFeatures;
try {
  SETTINGS.hiddenFeatures = ['tools', 'tunnels', 'passwordSave', 'multiexec', 'macro', 'split', 'local', 'logs'];
  await openBar('net'); O.netOff = shown();
  await openBar('sec'); O.secOff = shown();
  await openBar('term'); O.termOff = shown();
  await openBar('file'); O.fileOff = shown();
  await openBar('view'); O.viewOff = shown();
  O.featOk = !O.netOff.some((l) => /터널|포트|파일 서버/.test(l)) && O.secOff.join() === '알려진 호스트 관리…'
    && !O.termOff.includes('입력') && !O.fileOff.some((l) => /로컬 터미널|세션 로그/.test(l)) && !O.viewOff.includes('화면 분할');
  SETTINGS.hiddenFeatures = ['macro'];
  await openBar('term'); await hover('입력'); O.inputPartial = shown();
  O.partialOk = O.inputPartial.includes('MultiExec 켜기/끄기') && !O.inputPartial.includes('매크로');
  SETTINGS.hiddenFeatures = saved; hideMenu();

  // 키 누수: SSH 탭 열고 터미널에 포커스 → 메뉴 열고 ↓↓ Enter 대신 Esc → 터미널에 아무것도 안 감
  await openFake(2222); await until(() => focused()?.state === 'on' && focused().ws, 15000, 'ssh on');
  const s = focused(); s.term.focus(); await W(100);
  const sent = []; const ws = s.ws; const orig = ws.send.bind(ws); ws.send = (d) => { sent.push(d); return orig(d); };
  document.querySelector('#menubar [data-menu=view]').click(); await W(150);
  for (const key of ['ArrowDown', 'ArrowDown', 'ArrowRight', 'ArrowLeft', 'Escape'])
    { (document.activeElement || document).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })); await W(60); }
  O.menuClosed = document.querySelector('#ctxMenu').hidden;
  O.focusBack = s.pane.contains(document.activeElement);
  const data = () => sent.filter((d) => !(typeof d === 'string' && d.startsWith('{'))).length;
  O.leaked = data(); O.sentKinds = sent.map((d) => typeof d === 'string' ? d.slice(0, 40) : 'bin' + (d.byteLength ?? d.length));
  // 대조군: 메뉴가 닫힌 상태에서 같은 키는 터미널로 가야 함(검출 방법이 유효한지)
  document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', keyCode: 40, bubbles: true, cancelable: true })); await W(150);
  O.controlSent = data() - O.leaked;
  ws.send = orig;
  O.pass = O.featOk && O.partialOk && O.menuClosed && O.focusBack && O.leaked === 0 && O.controlSent > 0;
} catch (e) { O.errors.push(String(e && e.stack || e)); SETTINGS.hiddenFeatures = saved; }
return O;
