// #9 시험: SSH 게이트웨이(가짜 sshd 2222) 경유 Telnet(가짜 2323) — 처음 보는 게이트웨이 호스트 키에 확인 창이 떠야 함
// 실행: 빈 데이터 폴더(known_hosts 없음)로 웹 서버를 띄운 뒤  cat lib.js t_9.js | python cdp.py http://127.0.0.1:18022/ -
const R = {}; const errs = [];
window.addEventListener('error', (e) => errs.push(String(e.message)));
await until(() => typeof openSpec === 'function' && typeof DB !== 'undefined', 8000, 'app ready');
let hostkeyAsked = 0;
const hk = document.querySelector('#hostkeyDlg');
new MutationObserver(() => { if (hk.open) hostkeyAsked++; }).observe(hk, { attributes: true, attributeFilter: ['open'] });
autoAnswer();
DB.sessions.push({ id: 'gw9', type: 'ssh', name: 'gw9', host: '127.0.0.1', port: 2222, username: 'test', auth: 'password' });
openSpec({ id: 'tn9', type: 'telnet', quick: true, name: 'tn9', host: '127.0.0.1', port: 2323, gateway: 'gw9' });
const t = await until(() => tabs.find((x) => x.spec.id === 'tn9'), 3000, 'telnet tab');
await until(() => termText(t).includes('fake telnet'), 15000, 'telnet banner via gateway');
R.hostkeyAsked = hostkeyAsked;
R.state = t.state;
R.errors = errs;
return R;
