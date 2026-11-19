'use strict';
/* 도움말(단축키 안내) · 버전 정보 · 라이선스 창, 설정 창 세로 탭 전환 */

// ── 설정 창 탭 ─────────────────────────────────────────
function showDialogPane(dlg, name) {
  $$('.tdlg-tabs button', dlg).forEach((b) => {
    const on = b.dataset.pane === name;
    b.classList.toggle('on', on); b.setAttribute('aria-selected', on); b.tabIndex = on ? 0 : -1;
  });
  $$('.tdlg-body section', dlg).forEach((s) => s.classList.toggle('on', s.dataset.pane === name));
  $('.tdlg-body', dlg).scrollTop = 0;
}
function showSettingsPane(name) {
  showDialogPane($('#settingsDlg'), name);
  if (name === 'info') loadVersion().then(fillVersion);
  if (name === 'behavior') refreshUpdate();
}
function initDialogTabs(dlg, showPane) {
  const prefix = dlg.id === 'settingsDlg' ? '' : dlg.id + '-';
  $$('.tdlg-tabs button', dlg).forEach((b) => {
    b.id = dlg.id + '-tab-' + b.dataset.pane;
    b.setAttribute('role', 'tab'); b.setAttribute('aria-controls', prefix + 'pane-' + b.dataset.pane);
    b.onclick = () => showPane(b.dataset.pane);
  });
  $$('.tdlg-body section', dlg).forEach((s) => {
    s.id = prefix + 'pane-' + s.dataset.pane; s.setAttribute('role', 'tabpanel');
    s.setAttribute('aria-labelledby', dlg.id + '-tab-' + s.dataset.pane);
  });
  $('.tdlg-tabs', dlg).addEventListener('keydown', (e) => {   // 세로 탭: ↑↓ Home End
    const list = $$('.tdlg-tabs button', dlg).filter((b) => b.offsetParent);
    const i = list.indexOf(document.activeElement);
    const j = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: list.length - 1 }[e.key];
    if (i < 0 || j === undefined) return;
    e.preventDefault();
    const b = list[(j + list.length) % list.length];
    showPane(b.dataset.pane); b.focus();
  });
}
initDialogTabs($('#settingsDlg'), showSettingsPane);
initDialogTabs($('#guideDlg'), name => showDialogPane($('#guideDlg'), name));
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
}

// ── 창 열기 ───────────────────────────────────────────
function openHelp() { $('#helpDlg').showModal(); }
function openGuide() {
  const dlg = $('#guideDlg');
  $$('.tdlg-tabs button', dlg).forEach(b => {
    const features = (b.dataset.features || '').split(' ').filter(Boolean);
    b.classList.toggle('feat-off', features.length > 0 && features.every(f => !featureOn(f)));
  });
  showDialogPane(dlg, 'start');
  dlg.showModal();
}
function openAbout() { loadVersion().then(fillVersion); $('#aboutDlg').showModal(); }
paletteAction({ label: '사용법', run: () => openGuide() });

function fillUpdate(s) {
  $('#updateVersion').textContent = '현재 버전: v' + (s.current_version || '-');
  $('#updateLast').textContent = '마지막 확인: ' + (s.last_check ? fmtTime(s.last_check) : '-');
  $('#updateStatus').textContent = s.state === 'downloading' ? `v${s.version} 내려받는 중…` : s.checking ? '확인 중…' : s.state === 'available' ? `v${s.version} 있음` : s.state === 'ready' ? `v${s.version} 준비됨 — ${s.consent?.when === 'now' ? '재시작하면' : '종료하면'} 설치` : s.state === 'latest' ? '최신 버전입니다' : s.error || '확인 전';
  $('#updateCheck').disabled = !!s.checking;
  const notesButton = $('#updateNotes');
  notesButton.hidden = !(['available', 'ready'].includes(s.state) && typeof s.notes === 'string' && s.notes);
  notesButton.onclick = () => openUpdateNotes(s);
  const notesDlg = $('#updateNotesDlg');
  if (notesDlg.open && (notesDlg.dataset.version !== s.version || !['available', 'ready'].includes(s.state))) notesDlg.close();
  fillUpdateBanner(s);
  if (s.last_result?.ok === false) {
    toast(`업데이트 실패: ${s.last_result.error}`, 8000);
  } else if (s.last_result?.ok) {
    toast(`v${s.last_result.to}로 업데이트됨`, 8000);
    const url = s.last_result.notes_url;
    if (typeof url === 'string' && url.startsWith('https://github.com/rorena15/web-ssh-terminal/')) {
      const a = document.createElement('a');
      a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = ' · 변경 사항';
      $('#toast').append(a);
    }
  }
}
let updateShown = '', updateConfirm = '', updateDismissed = '', updateDeferred = '';
function appendUpdateNoteText(parent, value) {
  value = value.replace(/\[([^\]\n]+)\]\(https:\/\/[^\s)]*\)/g, '$1');
  for (const part of value.split(/(\*\*[^*]+\*\*)/g)) {
    if (!part) continue;
    const node = document.createElement(part.startsWith('**') && part.endsWith('**') ? 'strong' : 'span');
    node.textContent = node.tagName === 'STRONG' ? part.slice(2, -2) : part;
    parent.append(node);
  }
}
function renderUpdateNotes(body, notes) {
  body.replaceChildren();
  let list = null, item = null, sublist = null;
  for (const line of notes.split('\n')) {
    const match = /^(  )?- (.*)$/.exec(line);
    if (match) {
      if (!list) { list = document.createElement('ul'); body.append(list); }
      let target = list;
      if (match[1] && item) {
        if (!sublist) { sublist = document.createElement('ul'); item.append(sublist); }
        target = sublist;
      }
      const li = document.createElement('li'); appendUpdateNoteText(li, match[2]); target.append(li);
      if (!match[1] || !item) { item = li; sublist = null; }
    } else {
      list = null; item = null; sublist = null;
      if (!line.trim()) continue;
      const heading = line.startsWith('### ');
      const node = document.createElement(heading ? 'h4' : 'p');
      appendUpdateNoteText(node, heading ? line.slice(4) : line); body.append(node);
    }
  }
}
function openUpdateNotes(s) {
  const dlg = $('#updateNotesDlg');
  dlg.dataset.version = s.version;
  $('#updateNotesTitle').textContent = `W.S.T v${s.version} 변경 사항`;
  renderUpdateNotes($('#updateNotesBody'), typeof s.notes === 'string' ? s.notes : '');
  const actions = $('#updateNotesActions'); actions.replaceChildren();
  for (const [label, op, when] of [
    ['지금 재시작해서 설치', 'update_download', 'now'], ['종료할 때 설치', 'update_download', 'exit'],
    ['나중에', 'update_later'], ['이 버전 건너뛰기', 'update_skip'],
  ]) {
    if (s.state === 'ready' && (op === 'update_later' || (when && when === s.consent?.when))) continue;
    const b = document.createElement('button'); b.type = when === 'now' ? 'submit' : 'button'; b.textContent = label;
    if (when === 'now') { b.className = 'primary'; b.autofocus = true; }
    b.onclick = e => { e.preventDefault(); dlg.close(); updateAction(s.state === 'ready' && when === 'now' ? 'update_restart' : op, s.version, when); }; actions.append(b);
  }
  if (!dlg.open) dlg.showModal();
}
async function updateAction(op, version, when) {
  try { fillUpdate(await api.call(op, { version, ...(when ? { when } : {}) })); return true; }
  catch (e) { toast(e.message, 5000); return false; }
}
function fillUpdateBanner(s) {
  const bar = $('#updateBanner'), version = s.version;
  bar.replaceChildren(); bar.hidden = true;
  if (s.state !== 'ready' || s.consent?.when !== 'now') {
    updateConfirm = '';
    if ($('#updateRestartDlg').open) $('#updateRestartDlg').close('stale');
  }
  const text = (value) => { const span = document.createElement('span'); span.textContent = value; bar.append(span); };
  const button = (label, fn, primary = false) => {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = label;
    if (primary) b.className = 'primary';
    b.onclick = async () => {
      $$('button', bar).forEach(x => { x.disabled = true; });
      await fn();
      $$('button', bar).forEach(x => { x.disabled = false; });
    };
    bar.append(b);
  };
  if (s.prompt) {
    updateDismissed = ''; updateDeferred = '';
    text(`W.S.T v${version} 업데이트가 있습니다`);
    if (typeof s.notes === 'string' && s.notes) {
      const summary = s.notes.split('\n').find(line => line.startsWith('- '));
      if (summary) {
        const value = summary.slice(2), bold = /^\*\*([^*]+)\*\*/.exec(value);
        text(bold ? bold[1] : Array.from(value).length > 40 ? Array.from(value).slice(0, 40).join('') + '…' : value);
      }
      button('변경 사항', () => openUpdateNotes(s));
    } else if (typeof s.notes_url === 'string' && s.notes_url.startsWith('https://github.com/rorena15/web-ssh-terminal/')) {
      const a = document.createElement('a'); a.textContent = '변경 사항'; a.href = s.notes_url;
      a.target = '_blank'; a.rel = 'noopener noreferrer'; bar.append(a);
    }
    button('지금 재시작해서 설치', () => updateAction('update_download', version, 'now'), true);
    button('종료할 때 설치', () => updateAction('update_download', version, 'exit'));
    button('나중에', () => updateAction('update_later', version));
    button('이 버전 건너뛰기', () => updateAction('update_skip', version));
  } else if (s.state === 'downloading') {
    updateDismissed = '';
    text(`v${version} 내려받는 중…`);
  } else if (s.state === 'ready' && s.consent?.version === version && s.mode !== 'auto') {
    if (s.consent.when === 'now') {
      text(`v${version} 준비됨 — 재시작하면 설치`);
      const confirmRestart = () => {
        if ($('#updateRestartDlg').open) return;
        updateConfirm = version;
        const n = tabs.filter(t => t.state === 'on').length;
        const m = Object.values(TUNNEL_STATUS).filter(t => t.state !== 'off').length;
        const counts = [n && `열린 접속 ${n}개`, m && `터널 ${m}개`].filter(Boolean).join('와 ');
        $('#updateRestartText').textContent = (counts ? counts + '가 끊깁니다. ' : '') + '지금 재시작할까요?';
        dialogResult($('#updateRestartDlg')).then(async result => {
          if (result === 'stale') return;
          if (result === 'yes') {
            if (!await updateAction('update_restart', version)) updateConfirm = '';
          }
          else {
            updateDeferred = version;
            updateAction('update_download', version, 'exit');
          }
        });
      };
      button('지금 재시작', confirmRestart, true);
      button('종료할 때 설치', () => updateAction('update_download', version, 'exit'));
      if (updateConfirm !== version) confirmRestart();
    } else {
      if (updateShown !== version) { updateShown = version; toast(`종료하면 v${version}을 설치합니다`); }
      if (updateDeferred !== version) return;
      text(`v${version} 준비됨 — 종료하면 설치`);
    }
  } else if (s.state === 'error' && s.consent?.version === version && updateDismissed !== version) {
    text(`업데이트 실패: ${s.error}`);
    button('다시 시도', () => updateAction('update_download', version, s.consent.when), true);
    button('닫기', () => { updateDismissed = version; bar.hidden = true; });
  } else return;
  bar.hidden = false;
}
api.on('update', m => fillUpdate(m.status));
async function refreshUpdate() {
  try { fillUpdate(await api.call('update_status')); }
  catch (e) { $('#updateStatus').textContent = e.message; }
}
$('#updateCheck').onclick = async () => {
  try { fillUpdate(await api.call('update_check')); }
  catch (e) { $('#updateStatus').textContent = e.message; }
};
// 첫 연결 뒤 결과를 한 번 받고, 설정을 보는 동안에는 진행 상태를 갱신한다.
refreshUpdate();
setInterval(() => { if ($('#settingsDlg').open) refreshUpdate(); }, 2000);

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
