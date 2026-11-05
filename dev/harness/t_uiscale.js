// 화면 글자 크기(uiScale) 시험: 실제로 그려진 글자 높이가 UI 곳곳에서 배율만큼 커지는지 (11/4, Claude 작성)
// 실행: cat lib.js t_uiscale.js | PYTHONIOENCODING=utf-8 python cdp.py http://127.0.0.1:18022/ -
const O = { errors: [] };
window.addEventListener('error', (e) => O.errors.push(String(e.message)));
await until(() => typeof setUiScale === 'function' && typeof DB !== 'undefined', 8000, 'ready');
if (!DB.sessions.find((x) => x.id === 'uis1')) DB.sessions.push({ id: 'uis1', type: 'ssh', name: 'uis-host', host: '127.0.0.1', port: 2222, username: 'test', auth: 'password' });
renderTree();
const s = await openFake(); await W(300);
// 렌더된 글자 높이(px) = 텍스트 노드 범위의 높이
const textH = (sel) => {
  const el = document.querySelector(sel); if (!el) return null;
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: (n) => n.textContent.trim() ? 1 : 2 });
  const n = w.nextNode(); if (!n) return null;
  const r = document.createRange(); r.selectNodeContents(n); return r.getBoundingClientRect().height;
};
const T = { menu: '#menubar .mb', toolbar: '#quickGo', sftpDlg: '#settingsDlg h3', tree: '#tree .tr-row.sess .nm', tab: '.tab .label', status: '#sbText', vtab: '#vtabs .vt' };
const measure = () => { $('#settingsDlg').show(); const r = Object.fromEntries(Object.entries(T).map(([k, v]) => [k, textH(v)])); $('#settingsDlg').close(); return r; };
setSide('sessions'); setUiScale(1); await W(300);
const a = measure(); const termA = s.term.options.fontSize;
setUiScale(1.25); await W(400);
const b = measure(); const termB = s.term.options.fontSize;
O.ratios = Object.fromEntries(Object.keys(T).map((k) => [k, a[k] && b[k] ? +(b[k] / a[k]).toFixed(2) : null]));
O.allScaled = Object.values(O.ratios).every((r) => r != null && r >= 1.15);
O.termIndependent = termA === termB;
O.noHScroll = document.documentElement.scrollWidth <= document.documentElement.clientWidth;
DB.sessions = DB.sessions.filter((x) => x.id !== 'uis1'); renderTree();
setUiScale(1);
O.pass = O.allScaled && O.termIndependent && O.noHScroll && !O.errors.length;
return O;
