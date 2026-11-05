'use strict';
/* 도움말(단축키 안내) · 버전 정보 · 라이선스 창, 설정 창 세로 탭 전환 */

// ── 설정 창 탭 ─────────────────────────────────────────
function showSettingsPane(name) {
  const dlg = $('#settingsDlg');
  $$('.tdlg-tabs button', dlg).forEach((b) => {
    const on = b.dataset.pane === name;
    b.classList.toggle('on', on); b.setAttribute('aria-selected', on); b.tabIndex = on ? 0 : -1;
  });
  $$('.tdlg-body section', dlg).forEach((s) => s.classList.toggle('on', s.dataset.pane === name));
  if (name === 'info') loadVersion().then(fillVersion);
}
$$('#settingsDlg .tdlg-tabs button').forEach((b) => {
  b.setAttribute('role', 'tab'); b.setAttribute('aria-controls', 'pane-' + b.dataset.pane);
  b.onclick = () => showSettingsPane(b.dataset.pane);
});
$$('#settingsDlg .tdlg-body section').forEach((s) => { s.id = 'pane-' + s.dataset.pane; s.setAttribute('role', 'tabpanel'); });
$('#settingsDlg .tdlg-tabs').addEventListener('keydown', (e) => {   // 세로 탭: ↑↓ Home End
  const list = $$('#settingsDlg .tdlg-tabs button').filter((b) => b.offsetParent);
  const i = list.indexOf(document.activeElement);
  const j = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: list.length - 1 }[e.key];
  if (i < 0 || j === undefined) return;
  e.preventDefault();
  const b = list[(j + list.length) % list.length];
  showSettingsPane(b.dataset.pane); b.focus();
});
// 창을 열 때마다 첫 탭으로
new MutationObserver(() => { if ($('#settingsDlg').open) showSettingsPane('screen'); })
  .observe($('#settingsDlg'), { attributes: true, attributeFilter: ['open'] });

// ── 버전 ──────────────────────────────────────────────
let VERSION = null;
function loadVersion() {
  if (VERSION) return Promise.resolve(VERSION);
  return api.call('version', {}).then((v) => (VERSION = v)).catch(() => ({}));
}
function fillVersion(v) {
  const ver = v.version ? 'v' + v.version : '알 수 없음';
  $$('.about-ver').forEach((e) => { e.textContent = ver + (v.built ? ` · ${v.built}` : v.frozen === false ? ' · 소스 실행' : ''); });
  $('#abVersion').textContent = ver;
  $('#abBuilt').textContent = v.built || (v.frozen === false ? '소스에서 실행 중 (빌드 아님)' : '-');
  const libs = Object.entries(v.libs || {}).filter(([, x]) => x).map(([k, x]) => `${k} ${x}`).join(' · ');
  $('#abEnv').textContent = [v.python && 'Python ' + v.python, libs].filter(Boolean).join(' · ') || '-';
}

// ── 창 열기 ───────────────────────────────────────────
function openHelp() { $('#helpDlg').showModal(); }
function openAbout() { loadVersion().then(fillVersion); $('#aboutDlg').showModal(); }

let LICENSES = null;
async function openLicense() {
  const dlg = $('#licenseDlg');
  if (!dlg.open) dlg.showModal();
  if (!LICENSES) {
    let list;
    try {
      const r = await fetch('licenses/licenses.json');
      if (!r.ok) throw new Error(r.status);
      list = await r.json();
    } catch { $('.lic-meta', dlg).textContent = '라이선스 목록을 불러오지 못했습니다 (창을 다시 열면 재시도)'; return; }
    $('.lic-list', dlg).replaceChildren(...list.map((x, i) => {
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.type = 'button';
      b.innerHTML = '<b></b><span class="hint"></span>';
      b.querySelector('b').textContent = x.name;
      b.querySelector('span').textContent = x.license;
      b.onclick = () => showLicense(i);
      li.append(b);
      return li;
    }));
    LICENSES = list;                                  // 목록을 다 그린 뒤에만 기억
  }
  showLicense(0);
}
let licReq = 0;
async function showLicense(i) {
  const dlg = $('#licenseDlg'), x = LICENSES[i], req = ++licReq;   // 마지막으로 고른 항목만 본문에 반영
  if (!x) return;
  $$('.lic-list li', dlg).forEach((li, j) => { li.classList.toggle('on', j === i); li.firstChild.setAttribute('aria-current', j === i); });
  const meta = $('.lic-meta', dlg);
  meta.replaceChildren();
  const h = document.createElement('b'); h.textContent = x.name + (x.version && x.version !== 'vendored' ? ' ' + x.version : '');
  const lic = document.createElement('span'); lic.className = 'hint'; lic.textContent = ' · ' + x.license;
  meta.append(h, lic);
  if (x.url) { const a = document.createElement('div'); a.className = 'hint mono'; a.textContent = x.url; meta.append(a); }
  const pre = $('.lic-text', dlg);
  if (!x.files.length) { pre.textContent = x.note || '전문 미포함'; return; }
  pre.textContent = '불러오는 중…';
  try {
    const texts = await Promise.all(x.files.map((f) => fetch('licenses/' + f).then((r) => { if (!r.ok) throw new Error(r.status); return r.text(); })));
    if (req === licReq) pre.textContent = texts.join('\n\n' + '─'.repeat(60) + '\n\n');
  } catch { if (req === licReq) pre.textContent = '전문을 불러오지 못했습니다'; }
  pre.scrollTop = 0;
}

document.addEventListener('click', (e) => {
  const b = e.target.closest('.open-about, .open-license, .open-help');
  if (!b) return;
  if (b.classList.contains('open-about')) openAbout();
  else if (b.classList.contains('open-license')) openLicense();
  else openHelp();
});
