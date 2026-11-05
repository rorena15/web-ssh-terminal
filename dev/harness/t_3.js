// 3단계 시험: 이 PC 파일 탭(localfs), Rlogin(가짜 rlogind 2513), 탭 이름·diff 함수
// 실행: cat lib.js t_3.js | python cdp.py http://127.0.0.1:18022/ -
const R = {}; const errs = [];
window.addEventListener('error', (e) => errs.push(String(e.message)));
await until(() => typeof openTab === 'function' && typeof CAPS !== 'undefined' && CAPS.local, 8000, 'app ready');
// 1) 이 PC 파일 탭
openSpec({ id: 'localfs', type: 'localfs', quick: true, name: '이 PC' });
const lf = await until(() => tabs.find((t) => t.kind === 'localfs'), 3000, 'localfs tab');
await until(() => lf.state === 'on', 8000, 'localfs on');
await until(() => lf.sftp && lf.sftp.cwd && lf.sftp.view && lf.sftp.view.length, 8000, 'localfs list');
R.localfsCwd = lf.sftp.cwd; R.localfsCount = lf.sftp.view.length;
// 2) Rlogin
openSpec({ id: 'rl', type: 'rlogin', quick: true, host: '127.0.0.1', port: 2513, username: 'tester', name: 'rl' });
const rl = await until(() => tabs.find((t) => t.spec.id === 'rl'), 3000, 'rlogin tab');
await until(() => termText(rl).includes('rlogin ok tester'), 8000, 'rlogin banner');
typeIn(rl, 'hello rl\r');
await until(() => termText(rl).includes('hello rl\n'), 3000, 'rlogin echo');
R.rlogin = true;
// 3) diff (Myers) 함수가 있으면 간단 확인
if (typeof diffLines === 'function') {
  const d = diffLines(['a', 'b', 'c'], ['a', 'x', 'c']);
  R.diff = JSON.stringify(d).slice(0, 200);
}
R.errors = errs;
return R;
