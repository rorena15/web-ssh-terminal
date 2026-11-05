// GUI 개선 전후 비교용 화면 투어: python shot.py http://127.0.0.1:18022/ <출력접두어> ui_tour.js
// 빈 화면 → 세션 트리 → SSH 탭(모니터링 바) → SFTP → 분할 → 세션 편집 → 설정 → 팔레트 → 터널 (가짜 sshd 2222 필요)
await until(() => typeof openSpec === 'function' && typeof DB !== 'undefined', 8000, 'app ready');
if (!DB.sessions.find((s) => s.id === 'tour1')) {
  DB.sessions.push(
    { id: 'tour1', type: 'ssh', name: 'web-01', host: '127.0.0.1', port: 2222, username: 'test', auth: 'password', folder: '운영 서버' },
    { id: 'tour2', type: 'ssh', name: 'db-01', host: '127.0.0.1', port: 2222, username: 'test', auth: 'password', folder: '운영 서버', color: 'red' },
    { id: 'tour3', type: 'rdp', name: 'win-ad', host: '10.0.0.5', port: 3389, username: 'admin', folder: '운영 서버' },
    { id: 'tour4', type: 'telnet', name: 'switch-core', host: '10.0.0.1', port: 23, folder: '개발/네트워크' },
    { id: 'tour5', type: 'vnc', name: 'kiosk', host: '10.0.0.9', port: 5900, folder: '개발' },
  );
  openFolders.add('운영 서버'); openFolders.add('개발'); openFolders.add('개발/네트워크');
  renderTree();
}
await W(400);
// SHOT 01_start
autoAnswer();
openSpec(DB.sessions.find((s) => s.id === 'tour1'));
const t = await until(() => tabs.find((x) => x.spec.id === 'tour1' && x.state === 'on'), 10000, 'ssh on');
await until(() => termText(t).includes('$ '), 5000, 'prompt');
typeIn(t, 'echo hello from web-01\r');
await W(2500);
// SHOT 02_ssh_tab
if (t.sftp?.show) t.sftp.show(); else document.querySelector('[data-act=sftp], .sftp-toggle')?.click();
await W(1500);
// SHOT 03_sftp
setLayout('2v');
openSpec(DB.sessions.find((s) => s.id === 'tour2'));
await W(3000);
// SHOT 04_split
setLayout('1');
editSession(DB.sessions.find((s) => s.id === 'tour1'));
await W(500);
// SHOT 05_session_edit
document.querySelector('#sessionDlg').close();
document.querySelector('#tbSettings').click();
await W(500);
// SHOT 06_settings
document.querySelectorAll('dialog[open]').forEach((d) => d.close());
document.body.click();
openPalette();
await W(500);
// SHOT 07_palette
document.querySelectorAll('dialog[open]').forEach((d) => d.close());
document.querySelector('#tbTunnel').click();
await W(500);
// SHOT 08_tunnels
return 1;
