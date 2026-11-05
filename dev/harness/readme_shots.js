// README 촬영 순서 (저장소 루트, PowerShell; 서버 둘은 각각 별도 콘솔):
// python dev/harness/readme_seed.py dev/harness/run/readme_data
// python dev/harness/fake_sshd.py 2222 dev/harness/run/readme_data/sftp_root --demo
// $env:WEBSSH_DATA=(Resolve-Path dev/harness/run/readme_data).Path
// python server.py --no-token --no-tls --port 18022
// New-Item -ItemType Directory -Force docs/images
// python dev/harness/shot.py http://127.0.0.1:18022/ docs/images/x dev/harness/readme_shots.js
// x_main.png 등을 main.png 등으로 바꾼다. x_final.png는 종료 처리 뒤의 보조 이미지.
// 기존 seed가 있으면 다시 생성하지 않는다. SSH 2222, 앱 18022, 터널 18080/18081 필요.
// shot.py는 각 마커 직전에 준비한 화면을 찍는다. 각 구간은 별도 async 본문이다.
return (async () => {
  await until(() => typeof DB !== 'undefined' && DB.sessions?.some(s => s.id === 'readme-web-01'),
              10000, 'readme seed loaded (WEBSSH_DATA 확인)');
  if (tabs.length) throw new Error('촬영은 새 브라우저 페이지에서 시작하세요');
  autoAnswer('pw');
  store.set('uiTheme', 'light');
  store.set('termScheme', 'auto');
  applyTheme();
  toggleSidebar(false);
  setLayout('1');
  for (const folder of DB.folders) openFolders.add(folder);
  renderTree();
  window.__readme = {
    async settle() {
      await document.fonts.ready;
      await until(() => !document.querySelector('#toast').classList.contains('show'), 6000, 'toast dismissed');
      await W(400);
      if (document.querySelector('dialog[open]')) throw new Error('예상하지 않은 대화상자');
    },
    async connect(id, commands, expected) {
      const row = document.querySelector(`#tree [data-sid="${id}"]`);
      if (!row) throw new Error('세션 행 누락: ' + id);
      row.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      const s = await until(() => tabs.find(t => t.spec.id === id), 5000, id + ' tab');
      await until(() => s.state === 'on' && termText(s).includes('$ '), 15000, id + ' SSH');
      for (const cmd of commands) {
        const count = termText(s).split('$ ').length;
        typeIn(s, cmd + '\r');
        await until(() => termText(s).split('$ ').length > count, 5000, cmd + ' prompt');
      }
      await until(() => termText(s).includes(expected), 5000, id + ' demo output (--demo 확인)');
      return s;
    },
  };
  const r = window.__readme;
  r.web1 = await r.connect('readme-web-01', ['ls -la --color', 'systemctl status nginx'], 'ready to serve requests');
  r.web2 = await r.connect('readme-web-02', ['tail -n 20 /var/log/app.log', 'df -h'], '/backups');
  show(r.web1);
  setSide('sessions');
  document.querySelector('#tbSplit [data-layout="2v"]').click();
  await until(() => cells[0] === r.web1 && cells[1] === r.web2 && cells.every(s => s.state === 'on'),
              3000, 'web-01 left / web-02 right');
  await until(() => r.web1.mon?.cpu != null && document.querySelector('#statusbar').textContent.includes('CPU'),
              12000, 'remote monitoring');
  await until(() => document.querySelectorAll('#tree [data-sid]').length >= 5, 3000, 'expanded tree');
  await r.settle();
})();
// SHOT main
return (async () => {
  document.querySelector('#tbSplit [data-layout="1"]').click();
  show(window.__readme.web1);
  document.querySelector('#vtabs [data-side="sftp"]').click();
  const s = window.__readme.web1;
  await until(() => s.sftp, 5000, 'SFTP panel');
  await s.sftp.list('/home/test');
  await until(() => s.sftp.el.querySelectorAll('.sf-row[data-name]').length >= 6, 10000, 'SFTP fixtures');
  await window.__readme.settle();
})();
// SHOT sftp
return (async () => {
  setLayout('1');
  document.querySelector('#tbTunnel').click();
  const tunnel = DB.tunnels.find(t => t.id === 'readme-http');
  if (TUNNEL_STATUS[tunnel.id]?.state !== 'on') await toggleTunnel(tunnel);
  await until(() => TUNNEL_STATUS[tunnel.id]?.state === 'on' &&
              document.querySelectorAll('#tunnelList .tn-row').length >= 2 &&
              document.querySelector('#tunnelList .tn-row.on'), 15000, 'running tunnel');
  await window.__readme.settle();
})();
// SHOT tunnels
return (async () => {
  setLayout('1');
  document.querySelector('#vtabs [data-side="sessions"]').click();
  document.querySelector('#tbPalette').click();
  await until(() => document.querySelector('#paletteDlg').open &&
              document.querySelectorAll('#paletteDlg .pi').length >= 5, 5000, 'command palette');
  await W(400);
})();
// SHOT palette
return (async () => {
  document.querySelector('#paletteDlg').close();
  setLayout('1');
  document.querySelector('#tbSettings').click();
  await until(() => document.querySelector('#settingsDlg').open, 5000, 'settings');
  document.querySelector('#settingsDlg button[data-pane="features"]').click();
  await until(() => document.querySelector('#settingsDlg section[data-pane="features"]').classList.contains('on') &&
              document.querySelectorAll('#featureChecks input').length >= 10, 3000, 'feature settings');
  await W(400);
})();
// SHOT settings
return (async () => {
  document.querySelector('#settingsDlg').close('cancel');
  await api.call('tunnelStop', { tid: 'readme-http' });
  clearInterval(window.__auto);
  delete window.__auto;
  await window.__readme.settle();
  console.log('README shots complete: main, sftp, tunnels, palette, settings');
})();
