// 11/19 업데이트 변경 내용 표시(명세 7.2) 화면 시험 (Claude 검증). t_update_banner.js와 같은 방식.
// 실행: cat lib.js t_update_notes_ui.js | PYTHONIOENCODING=utf-8 python cdp.py http://127.0.0.1:18042/ -
const O = { errors: [] };
window.addEventListener('error', (e) => O.errors.push(String(e.message)));
await until(() => typeof fillUpdate === 'function' && typeof DB !== 'undefined', 8000, 'ready');
const calls = []; const oc = api.call.bind(api);
api.call = async (op, args) => { if (op.startsWith('update_') && op !== 'update_status') { calls.push([op, args]); return { state: 'downloading', version: args.version, mode: 'notify', notes: '' }; } return oc(op, args); };
const NOTES = "### 변경 사항\n- **업데이트를 설치 전에 묻습니다.** 새 버전이 있으면 메뉴 아래 알림 띠에 버전과 [변경 사항] 링크가 뜨고, 다음 중 하나를 고릅니다.\n  - **지금 재시작해서 설치**: 내려받은 뒤 확인 창(열린 접속·터널이 끊긴다는 안내)을 거쳐 W.S.T를 닫고 설치한 다음 다시 엽니다.\n  - **종료할 때 설치**: 내려받아 두고 W.S.T를 닫을 때 설치합니다.\n  - **나중에**: 다음 날 다시 알립니다.\n  - **이 버전 건너뛰기**: 이 버전은 다시 묻지 않고, 더 새 버전이 나오면 알립니다.\n  - 고르기 전에는 업데이트 파일을 내려받지 않습니다(새 버전 여부와 서명된 파일 목록만 확인).\n  - 알림 띠에 변경 내용 첫 줄이 보이고, [변경 사항]을 누르면 앱 안에서 이번 버전의 변경 내용 전체를 볼 수 있습니다. 변경 내용은 서명된 파일 목록에 함께 실려 오므로 서명을 확인한 내용만 표시합니다(v1.4.0 다음 버전부터 보입니다).\n- **⚙설정 → 업데이트**에서 방식을 고릅니다: 알림 후 설치(기본) · 묻지 않고 자동 설치(v1.2~v1.3 방식) · 확인 안 함. 예전에 자동 업데이트를 꺼 두었다면 \"확인 안 함\"으로 이어집니다. [지금 확인]은 어느 방식에서든 동작합니다.\n- 서명·버전·파일 해시 검증 규칙은 그대로입니다.\n\n### 알아 둘 점\n- v1.2.0~v1.3.0에서 v1.4.0으로 올라가는 이번 한 번은 예전 방식대로 W.S.T 종료 시 자동으로 설치됩니다. v1.4.0부터 설치 전에 묻습니다.\n- v1.1.1 이하는 한 번 직접 설치하세요.\n\n### 알려진 문제\n[SECURITY.md](https://github.com/rorena15/web-ssh-terminal/blob/main/SECURITY.md#known-issues) 참고.\n- 주입 시험 <img src=x onerror=alert(1)> [링크](https://evil.example/)";
const s = { current_version: '1.3.0', mode: 'notify', checking: false, last_check: Date.now() / 1000, state: 'available', version: '1.4.0', prompt: true, consent: null, notes_url: 'https://github.com/rorena15/web-ssh-terminal/releases/tag/v1.4.0', notes: NOTES };
fillUpdate(s);
const bar = $('#updateBanner');
O.summary = bar.textContent.includes('업데이트를 설치 전에 묻습니다') && !bar.textContent.includes('**');
const nb = [...$$('#updateBanner button, #updateBanner a')].find(b => b.textContent.includes('변경 사항'));
nb?.click(); await W(200);
const dlg = $('#updateNotesDlg');
O.dialogOpen = dlg.open && $('#updateNotesTitle').textContent === 'W.S.T v1.4.0 변경 사항';
O.hasList = $$('#updateNotesBody li').length >= 6 && $$('#updateNotesBody li li').length >= 4;
O.hasStrong = $$('#updateNotesBody strong').length >= 2;
O.hasHeading = [...$$('#updateNotesBody *')].some(e => e.textContent.trim() === '변경 사항' && /^H/.test(e.tagName));
O.noLinks = !$('#updateNotesBody a');
O.noImg = !$('#updateNotesBody img') && $('#updateNotesBody').textContent.includes('<img src=x');
O.fourButtons = $$('#updateNotesActions button').length === 4;
console.log('SHOT:notes');
await W(300);
$$('#updateNotesActions button')[1].click(); await W(150);
O.exitFromDlg = !dlg.open && JSON.stringify(calls.at(-1)) === JSON.stringify(['update_download', { version: '1.4.0', when: 'exit' }]);
// notes 없으면 링크만
fillUpdate({ ...s, notes: '' });
O.linkFallback = !!$('#updateBanner a[href^="https://github.com/rorena15/web-ssh-terminal/"]');
api.call = oc;
O.pass = Object.entries(O).every(([k, v]) => k === 'errors' ? !v.length : v === true);
return O;
