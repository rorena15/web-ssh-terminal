// D5 시험: 키 암호 실패(passphrase:) 시 메모리에 캐시된 틀린 키 암호를 지워야 함
// 실행: (echo "const KEY='...';"; cat dev/harness/lib.js dev/harness/t_d5.js) | python dev/harness/cdp.py http://127.0.0.1:18022/ -
const R = {
  pass: false,
  prompts: [],
  t1WrongMsg: false,
  promptedBeforeSendOnNewTab: false,
  t2SentWrongAgain: false,
  t2AfterRight: '',
  errors: [],
};
window.addEventListener('error', (e) => R.errors.push(String(e.message)));

await until(() => typeof openSpec === 'function' && typeof DB !== 'undefined', 8000, 'app ready');

const sd = document.querySelector('#secretDlg');
const hk = document.querySelector('#hostkeyDlg');
const spec = {
  id: 'd5_key',
  type: 'ssh',
  quick: true,
  name: 'd5_key',
  host: '127.0.0.1',
  port: 2222,
  username: 'test',
  auth: 'keyfile',
  keyPath: KEY,
};

// 1번째 창: 'wrong' 입력(OK) → 서버가 passphrase: 오류 반환 → 2번째 창(재질문): 취소(cancel)
// → 새 탭 openSpec(spec) 호출 시 틀린 암호를 서버로 다시 보내지 않고 3번째 창이 바로 떠야 함 → 'right' 입력(OK)
const actions = [
  { type: 'ok', value: 'wrong' },
  { type: 'cancel' },
  { type: 'ok', value: 'right' },
];
let step = 0;
let t1 = null;

const timer = setInterval(() => {
  if (hk && hk.open) hk.querySelector('button[value=yes]').click();
  if (sd && sd.open && !sd.__busy && step < actions.length) {
    sd.__busy = true;
    const act = actions[step++];
    const labels = [...sd.querySelectorAll('#secFields label, #secFields input')]
      .map((e) => e.textContent || e.name)
      .join('|');
    const otherTabs = tabs.filter((x) => x !== t1);
    const wrongAlreadyInNewTab = otherTabs.some((x) => termText(x).includes('키 암호가 틀렸습니다'));
    R.prompts.push({ step, action: act.type, labels, wrongAlreadyInNewTab });

    setTimeout(() => {
      if (act.type === 'ok') {
        sd.querySelectorAll('#secFields input').forEach((i) => {
          i.value = act.value;
        });
        sd.querySelector('button[value=ok]').click();
      } else {
        sd.querySelector('button[value=cancel]').click();
      }
      sd.__busy = false;
    }, 30);
  }
}, 50);

try {
  openSpec(spec);
  t1 = await until(() => tabs.find((x) => x.spec && x.spec.id === 'd5_key'), 4000, 'first tab');

  // 1번째 질문('wrong') 후 서버가 키 암호 오류를 돌려주고 2번째 질문에서 cancel을 누를 때까지 대기
  await until(() => step >= 2 && !sd.open, 15000, 'second prompt canceled');
  await W(300);
  R.t1WrongMsg = termText(t1).includes('키 암호가 틀렸습니다');

  // 같은 세션(같은 spec)으로 새 탭 열기
  openSpec(spec);

  // 3번째 질문이 떠서 'right'를 넣을 때까지 대기
  await until(() => step >= 3, 8000, 'third prompt on new tab');
  const t2 = await until(() => tabs.find((x) => x !== t1 && x.spec && x.spec.id === 'd5_key'), 5000, 'second tab');
  await until(() => /인증 실패|접속 실패|\$ /.test(termText(t2)), 15000, 't2 finished auth');
  await W(300);

  const t2Txt = termText(t2);
  R.promptedBeforeSendOnNewTab = R.prompts.length === 3 && R.prompts[2].wrongAlreadyInNewTab === false;
  R.t2SentWrongAgain = t2Txt.includes('키 암호가 틀렸습니다');
  R.t2AfterRight = /인증 실패/.test(t2Txt) ? 'auth failed (key decrypted with right passphrase)' : t2Txt.slice(-200);

  R.pass =
    R.t1WrongMsg === true &&
    R.prompts.length === 3 &&
    R.promptedBeforeSendOnNewTab === true &&
    R.t2SentWrongAgain === false &&
    /인증 실패/.test(t2Txt) &&
    R.errors.length === 0;
} catch (e) {
  R.errors.push(String(e && e.message ? e.message : e));
} finally {
  clearInterval(timer);
}

return R;
