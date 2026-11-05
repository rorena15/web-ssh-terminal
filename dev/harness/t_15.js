// #15 시험: 개인키 파일 암호를 틀리면 다시 물어야 함 (예전: "개인키를 읽을 수 없습니다"로 끝)
// 실행: KEY=<암호 right로 만든 OpenSSH 키 경로>  →  (echo "const KEY='...';"; cat lib.js t_15.js) | python cdp.py http://127.0.0.1:18022/ -
const R = { prompts: [] }; const errs = [];
window.addEventListener('error', (e) => errs.push(String(e.message)));
await until(() => typeof openSpec === 'function' && typeof DB !== 'undefined', 8000, 'app ready');
const answers = ['wrong', 'right'];
const sd = document.querySelector('#secretDlg');
const hk = document.querySelector('#hostkeyDlg');
const timer = setInterval(() => {
  if (hk.open) hk.querySelector('button[value=yes]').click();
  if (sd.open && !sd.__done && answers.length) {
    sd.__done = true;
    R.prompts.push([...sd.querySelectorAll('#secFields label, #secFields input')].map((e) => e.textContent || e.name).join('|'));
    const v = answers.shift();
    setTimeout(() => {
      sd.querySelectorAll('#secFields input').forEach((i) => { i.value = v; });
      sd.querySelector('button[value=ok]').click();
      sd.__done = false;
    }, 30);
  }
}, 50);
openSpec({ id: 'k15', type: 'ssh', quick: true, name: 'k15', host: '127.0.0.1', port: 2222, username: 'test', auth: 'keyfile', keyPath: KEY });
const t = await until(() => tabs.find((x) => x.spec.id === 'k15'), 3000, 'tab');
await until(() => !answers.length && /인증 실패|접속 실패|\$ /.test(termText(t)), 20000, 'after two answers');
await W(500);
clearInterval(timer);
R.wrongMsg = termText(t).includes('키 암호가 틀렸습니다');
R.afterRight = /인증 실패/.test(termText(t)) ? 'auth failed (key loaded; fake sshd is password-only)' : termText(t).slice(-200);
R.errors = errs;
return R;
