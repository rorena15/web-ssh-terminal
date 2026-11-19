// 11/19 업데이트 알림 띠·설정 선택 상자 (Claude 검증). 소스 실행 서버에서는 업데이트가 꺼져 있으므로
// 프런트 상태 전이만 fillUpdate(가짜 status)로 확인하고, op 호출은 api.call을 가로채 기록한다.
// 실행: cat lib.js t_update_banner.js | PYTHONIOENCODING=utf-8 python cdp.py http://127.0.0.1:18042/ -
const O = { errors: [] };
window.addEventListener('error', (e) => O.errors.push(String(e.message)));
await until(() => typeof fillUpdate === 'function' && typeof DB !== 'undefined', 8000, 'ready');
const calls = []; const oc = api.call.bind(api);
api.call = async (op, args) => { if (op.startsWith('update_') && op !== 'update_status') { calls.push([op, args]); return { state: 'downloading', version: args.version, mode: 'notify' }; } return oc(op, args); };
const bar = $('#updateBanner');
const btns = () => $$('#updateBanner button').map(b => b.textContent);
const base = { current_version: '1.3.0', mode: 'notify', checking: false, last_check: Date.now() / 1000 };
// 1) available + prompt
fillUpdate({ ...base, state: 'available', version: '9.9.9', prompt: true, consent: null, notes_url: 'https://github.com/rorena15/web-ssh-terminal/releases/tag/v9.9.9' });
O.promptShown = !bar.hidden && bar.textContent.includes('W.S.T v9.9.9 업데이트가 있습니다');
O.fourButtons = JSON.stringify(btns()) === JSON.stringify(['지금 재시작해서 설치', '종료할 때 설치', '나중에', '이 버전 건너뛰기']);
O.primaryFirst = $('#updateBanner button').classList.contains('primary');
const a = $('#updateBanner a'); O.notesLink = !!a && a.rel.includes('noopener') && a.target === '_blank';
// 2) 링크 제한·XSS
fillUpdate({ ...base, state: 'available', version: '<img src=x onerror=alert(1)>', prompt: true, notes_url: 'https://evil.example/' });
O.noForeignLink = !$('#updateBanner a'); O.noInjectedImg = !$('#updateBanner img');
// 3) 버튼 → op
fillUpdate({ ...base, state: 'available', version: '9.9.9', prompt: true, notes_url: '' });
$$('#updateBanner button')[1].click(); await W(100);
O.exitOp = JSON.stringify(calls.at(-1)) === JSON.stringify(['update_download', { version: '9.9.9', when: 'exit' }]);
fillUpdate({ ...base, state: 'available', version: '9.9.9', prompt: true, notes_url: '' });
$$('#updateBanner button')[2].click(); await W(100);
O.laterOp = calls.at(-1)?.[0] === 'update_later';
// 4) prompt 거짓(나중에·건너뛰기 뒤) → 띠 없음
fillUpdate({ ...base, state: 'available', version: '9.9.9', prompt: false });
O.hiddenWhenNoPrompt = bar.hidden;
// 5) downloading
fillUpdate({ ...base, state: 'downloading', version: '9.9.9', prompt: false });
O.downloading = !bar.hidden && bar.textContent.includes('v9.9.9 내려받는 중') && btns().length === 0;
// 6) ready + now → 확인 창, 취소하면 exit로
fillUpdate({ ...base, state: 'ready', version: '9.9.9', prompt: false, consent: { version: '9.9.9', when: 'now' } });
await W(100);
O.restartDlg = $('#updateRestartDlg').open && $('#updateRestartText').textContent.includes('지금 재시작할까요?');
$('#updateRestartDlg button[value=cancel]').click(); await W(150);
O.cancelToExit = JSON.stringify(calls.at(-1)) === JSON.stringify(['update_download', { version: '9.9.9', when: 'exit' }]);
// 7) ready + now 다시 → 확인 → restart op
fillUpdate({ ...base, state: 'available', version: '9.9.8', prompt: true });
fillUpdate({ ...base, state: 'ready', version: '9.9.8', prompt: false, consent: { version: '9.9.8', when: 'now' } });
await W(100);
$('#updateRestartDlg button[value=yes]').click(); await W(150);
O.restartOp = JSON.stringify(calls.at(-1)) === JSON.stringify(['update_restart', { version: '9.9.8' }]);
// 8) error + 다시 시도
fillUpdate({ ...base, state: 'error', version: '9.9.7', error: '받은 파일 검증 실패', prompt: false, consent: { version: '9.9.7', when: 'exit' } });
O.errorBar = !bar.hidden && bar.textContent.includes('업데이트 실패: 받은 파일 검증 실패') && btns().includes('다시 시도') && btns().includes('닫기');
// 9) auto 모드 ready → 띠 없음
fillUpdate({ ...base, mode: 'auto', state: 'ready', version: '9.9.6', prompt: false, consent: null });
O.autoNoBar = bar.hidden;
// 10) 설정 선택 상자
$('#tbSettings').click(); await until(() => $('#settingsDlg').open, 3000, 'settings');
const sel = $('#settingsDlg select[name=updateMode]');
O.select = !!sel && JSON.stringify([...sel.options].map(o => o.value)) === '["notify","auto","off"]' && sel.value === (SETTINGS.updateMode || 'notify');
O.noOldCheckbox = !$('#settingsDlg input[name=autoUpdate]');
$('#settingsDlg button[value=cancel]').click();
api.call = oc;
O.pass = Object.entries(O).every(([k, v]) => k === 'errors' ? !v.length : v === true);
return O;
