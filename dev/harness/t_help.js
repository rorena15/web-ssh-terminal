// 도움말·버전 정보·라이선스 창, 설정 창 세로 탭 시험 (11/4, Claude 작성)
// 실행: cat lib.js t_help.js | PYTHONIOENCODING=utf-8 python cdp.py http://127.0.0.1:18022/ -
const O = { errors: [] };
window.addEventListener('error', (e) => O.errors.push(String(e.message)));
await until(() => typeof openHelp === 'function' && typeof DB !== 'undefined', 8000, 'ready');
const menu = async (name, label) => {
  document.querySelector(`#menubar [data-menu=${name}]`).click(); await W(150);
  const b = [...document.querySelectorAll('#ctxMenu button')].find((x) => x.textContent.includes(label));
  b?.click(); await W(300); return !!b;
};
let toasted = false; const ot = window.toast; window.toast = (...a) => { toasted = true; return ot(...a); };
O.helpItem = await menu('help', '단축키 안내');
O.helpDlg = $('#helpDlg').open && !toasted && $$('#helpDlg table.keys tr').length >= 15;
$('#helpDlg').close();
O.aboutItem = await menu('help', '버전 정보');
await until(() => /v\d/.test($('#abVersion').textContent), 4000, 'version');
O.aboutDlg = $('#aboutDlg').open && /v\d+\.\d+/.test($('#abVersion').textContent) && /Python/.test($('#abEnv').textContent);
$('#aboutDlg .open-license').click(); await W(400);
await until(() => $$('#licenseDlg .lic-list li').length > 0, 4000, 'list');
O.licenseFromAbout = $('#licenseDlg').open && $$('#licenseDlg .lic-list li').length >= 10;
const pi = $$('#licenseDlg .lic-list li').findIndex((li) => /paramiko/.test(li.textContent));
$$('#licenseDlg .lic-list li')[pi].querySelector('button').click();
await until(() => /GNU|LESSER/i.test($('#licenseDlg .lic-text').textContent), 4000, 'paramiko text');
O.paramikoText = true;
const xi = $$('#licenseDlg .lic-list li').findIndex((li) => /xterm/.test(li.textContent));
$$('#licenseDlg .lic-list li')[xi].querySelector('button').click(); await W(200);
O.xtermNoFake = /미포함/.test($('#licenseDlg .lic-text').textContent);
$('#licenseDlg').close(); $('#aboutDlg').close();
// 설정 창
$('#tbSettings').click(); await until(() => $('#settingsDlg').open, 3000, 'settings');
const tabs = $$('#settingsDlg .tdlg-tabs button').filter((b) => b.offsetParent);
const rect0 = $('#settingsDlg').getBoundingClientRect();
O.settingsTabs = tabs.length >= 6 && $('#settingsDlg .tdlg-tabs button.on').dataset.pane === 'screen';
let sizeStable = true, onePane = true;
for (const b of tabs) {
  b.click(); await W(80);
  const r = $('#settingsDlg').getBoundingClientRect();
  if (Math.abs(r.height - rect0.height) > 1 || Math.abs(r.width - rect0.width) > 1) sizeStable = false;
  if ($$('#settingsDlg .tdlg-body section.on').length !== 1) onePane = false;
}
O.sizeStable = sizeStable; O.onePane = onePane;
await until(() => /v\d/.test($('#settingsDlg .about-ver').textContent), 4000, 'info ver');
O.infoVersion = true;
O.noHScroll = document.documentElement.scrollWidth <= document.documentElement.clientWidth;
$('#settingsDlg button[value=cancel]').click(); await W(200);
O.reopenFirstTab = (() => { $('#tbSettings').click(); return true; })();
await W(300);
O.reopenFirstTab = $('#settingsDlg .tdlg-tabs button.on').dataset.pane === 'screen';
$('#settingsDlg button[value=cancel]').click();
window.toast = ot;
O.pass = Object.entries(O).every(([k, v]) => k === 'errors' ? !v.length : v === true);
return O;
