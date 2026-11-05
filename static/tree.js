'use strict';
/* 세션 폴더 트리 · 세션 편집 · 세션 파일 가져오기 · 설정 · 시작 */

const ICON = PROTOCOL_LABELS;
let treeSel = null;               // {kind:'session'|'folder', id|path}
let openFolders = new Set(store.get('openFolders', []));

function allFolders() {
  const set = new Set(DB.folders || []);
  for (const s of allSessions()) if (s.folder) set.add(s.folder);
  for (const f of [...set]) {                     // 상위 폴더도 포함
    const parts = f.split('/');
    for (let i = 1; i < parts.length; i++) set.add(parts.slice(0, i).join('/'));
  }
  return [...set].sort((a, b) => a.localeCompare(b, 'ko'));
}
const sessName = (s) => s.name || (s.type === 'local' ? shellName(s.shell) : targetStr(s));
const TYPE_NAME = { rdp: 'RDP', sftp: 'SFTP', telnet: 'Telnet', rlogin: 'Rlogin', serial: 'Serial', ftp: 'FTP', vnc: 'VNC', mosh: 'Mosh' };
const sessSub = (s) => s.type === 'local' ? '로컬 터미널'
  : s.type === 'serial' ? `${s.com} · ${s.baud || 9600} ${s.bits || 8}${s.parity || 'N'}${s.stop || 1}`
  : targetStr({ ...s, port: s.port === DEFAULT_PORT[s.type] ? 22 : s.port }) + (TYPE_NAME[s.type] ? ' · ' + TYPE_NAME[s.type] : '') + (s.jump?.host || s.gateway ? ' · 경유' : '');

// ── 트리 그리기 ─────────────────────────────────────────
function renderTree() {
  const box = $('#tree');
  const q = $('#treeSearch').value.trim().toLowerCase();
  box.innerHTML = '';
  const match = (s) => !q || [s.name, s.host, s.username, s.folder].some((v) => (v || '').toLowerCase().includes(q));
  const folders = allFolders();
  const sessionsIn = (f) => allSessions().filter((s) => (s.folder || '') === f && match(s))
    .sort((a, b) => sessName(a).localeCompare(sessName(b), 'ko'));
  const childFolders = (f) => folders.filter((x) => (f ? x.startsWith(f + '/') && !x.slice(f.length + 1).includes('/') : !x.includes('/')));
  const hasMatch = (f) => sessionsIn(f).length || childFolders(f).some(hasMatch);

  const addFolder = (f, depth) => {
    if (q && !hasMatch(f)) return;
    const open = q ? true : openFolders.has(f);
    const row = document.createElement('div');
    row.className = 'tr-row folder';
    row.style.paddingLeft = (6 + depth * 14) / 12 + 'rem';
    row.innerHTML = `<span class="tw">${open ? '▾' : '▸'}</span><span class="ic">${uiIcon('folder')}</span><span class="nm"></span><span class="cnt"></span>`;
    row.querySelector('.nm').textContent = f.split('/').pop();
    const n = allSessions().filter((s) => (s.folder || '') === f || (s.folder || '').startsWith(f + '/')).length;
    const connected = allSessions().filter(s => ((s.folder || '') === f || (s.folder || '').startsWith(f + '/')) && sessionState(s) === 'on').length;
    row.querySelector('.cnt').textContent = connected ? n + ' · ' + connected + ' 접속' : String(n);
    row.dataset.folder = f;
    row.draggable = true;
    row.onclick = () => { selectTree({ kind: 'folder', path: f }); toggleFolder(f); };
    row.oncontextmenu = (e) => { e.preventDefault(); selectTree({ kind: 'folder', path: f }); folderMenu(f, e.clientX, e.clientY); };
    dnd(row, { kind: 'folder', path: f }, f);
    box.appendChild(row);
    if (!open) return;
    childFolders(f).forEach((c) => addFolder(c, depth + 1));
    sessionsIn(f).forEach((s) => addSession(s, depth + 1));
  };
  const addSession = (s, depth) => {
    const row = document.createElement('div');
    row.className = 'tr-row sess';
    row.style.paddingLeft = (6 + depth * 14 + 14) / 12 + 'rem';
    row.innerHTML = `<span class="lc"></span>${sessionMarkup(s, sessName(s), sessionState(s))}<span class="sub"></span>`;
    const lc = LABEL_COLORS[s.color];
    if (lc && s.color !== 'red') { row.querySelector('.lc').style.background = lc[1]; row.querySelector('.lc').title = lc[0]; }

    row.querySelector('.label').classList.add('nm');
    row.querySelector('.sub').textContent = s.host || s.com || '';
    row.title = `${sessName(s)}\n${sessSub(s)}${s.log ? '\n세션 로그 저장' : ''}`;
    row.dataset.sid = s.id;
    row.draggable = true;
    row.onclick = () => selectTree({ kind: 'session', id: s.id });
    row.ondblclick = () => openSpec(s);
    row.oncontextmenu = (e) => { e.preventDefault(); selectTree({ kind: 'session', id: s.id }); sessionMenu(s, e.clientX, e.clientY); };
    dnd(row, { kind: 'session', id: s.id }, s.folder || '');
    box.appendChild(row);
  };

  childFolders('').forEach((f) => addFolder(f, 0));
  sessionsIn('').forEach((s) => addSession(s, 0));
  if (!box.children.length) {
    box.innerHTML = q ? '<div class="side-empty">검색 결과 없음</div>'
      : '<div class="side-empty">저장된 세션이 없습니다.<br>＋ 로 만들거나 ⤓ 로 세션 파일을 가져오세요.</div>';
  }
  paintTreeSel();
  $('#folderList').innerHTML = folders.map((f) => `<option value="${escapeHtml(f)}">`).join('');
}

function toggleFolder(f) {
  openFolders.has(f) ? openFolders.delete(f) : openFolders.add(f);
  store.set('openFolders', [...openFolders]);
  renderTree();
}
function selectTree(sel) { treeSel = sel; paintTreeSel(); }
function paintTreeSel() {
  $$('#tree .tr-row').forEach((r) => r.classList.toggle('sel',
    !!treeSel && (treeSel.kind === 'session' ? r.dataset.sid === treeSel.id : r.dataset.folder === treeSel.path)));
}
$('#treeSearch').addEventListener('input', renderTree);
// 검색창: ↓ = 트리로, Enter = 첫 번째(또는 선택한) 세션 열기, Esc = 지우기
$('#treeSearch').addEventListener('keydown', (e) => {
  const rows = $$('#tree .tr-row.sess');
  if (e.key === 'ArrowDown' && rows.length) { e.preventDefault(); moveTreeSel(1); $('#tree').focus(); }
  else if (e.key === 'Enter') {
    e.preventDefault();
    const s = treeSel?.kind === 'session' && rows.some((r) => r.dataset.sid === treeSel.id) ? findSession(treeSel.id) : findSession(rows[0]?.dataset.sid);
    if (s) openSpec(s);
  } else if (e.key === 'Escape') { e.target.value = ''; renderTree(); }
});
function moveTreeSel(d) {
  const rows = $$('#tree .tr-row');
  if (!rows.length) return;
  let i = rows.findIndex((r) => r.classList.contains('sel'));
  i = i < 0 ? (d > 0 ? 0 : rows.length - 1) : Math.max(0, Math.min(rows.length - 1, i + d));
  const r = rows[i];
  selectTree(r.dataset.sid ? { kind: 'session', id: r.dataset.sid } : { kind: 'folder', path: r.dataset.folder });
  r.scrollIntoView({ block: 'nearest' });
}
$('#tree').addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); return moveTreeSel(e.key === 'ArrowDown' ? 1 : -1); }
  if (e.key === 'Home' || e.key === 'End') { e.preventDefault(); return moveTreeSel(e.key === 'Home' ? -1e9 : 1e9); }
  if (!treeSel) return;
  if (treeSel.kind === 'folder') {
    const f = treeSel.path, open = openFolders.has(f) || $('#treeSearch').value.trim();
    if ((e.key === 'ArrowRight' && !open) || (e.key === 'ArrowLeft' && open) || e.key === 'Enter') { e.preventDefault(); toggleFolder(f); }
    else if (e.key === 'ArrowLeft' && f.includes('/')) { selectTree({ kind: 'folder', path: f.split('/').slice(0, -1).join('/') }); }
    else if (e.key === 'F2') renameFolder(f);
    else if (e.key === 'Delete') deleteFolder(f);
    return;
  }
  const s = findSession(treeSel.id);
  if (!s) return;
  if (e.key === 'Enter') openSpec(s);
  else if (e.key === 'F2' && !s.shared) editSession(s);
  else if (e.key === 'Delete' && !s.shared) deleteSession(s);
  else if (e.key === 'ArrowLeft' && s.folder) selectTree({ kind: 'folder', path: s.folder });
});
$('#tree').addEventListener('contextmenu', (e) => {
  if (e.target.closest('.tr-row')) return;
  e.preventDefault();
  showMenu(e.clientX, e.clientY, [
    { label: '새 세션', action: () => editSession(null, '') },
    { label: '새 폴더', action: () => newFolder('') },
    { label: '세션 파일 가져오기 (.mxtsessions / .ini / .json)…', action: () => $('#importFile').click() },
  ]);
});

// 드래그&드롭으로 폴더 이동
let dragItem = null;
function dnd(row, item, folderOfTarget) {
  row.addEventListener('dragstart', (e) => { dragItem = item; e.dataTransfer.effectAllowed = 'move'; });
  row.addEventListener('dragend', () => { dragItem = null; $$('#tree .drop').forEach((r) => r.classList.remove('drop')); });
  row.addEventListener('dragover', (e) => { if (dragItem) { e.preventDefault(); row.classList.add('drop'); } });
  row.addEventListener('dragleave', () => row.classList.remove('drop'));
  row.addEventListener('drop', (e) => {
    e.preventDefault(); e.stopPropagation();
    row.classList.remove('drop');
    moveTo(dragItem, item.kind === 'folder' ? item.path : folderOfTarget);
  });
}
$('#tree').addEventListener('dragover', (e) => { if (dragItem) e.preventDefault(); });
$('#tree').addEventListener('drop', (e) => { e.preventDefault(); if (dragItem) moveTo(dragItem, ''); });

function moveTo(item, folder) {
  if (!item) return;
  if (item.kind === 'session') {
    const s = findSession(item.id);
    if (!s || (s.folder || '') === folder) return;
    s.folder = folder;
  } else {
    const src = item.path;
    if (folder === src || folder.startsWith(src + '/')) return;
    const dst = (folder ? folder + '/' : '') + src.split('/').pop();
    if (dst === src) return;
    renameFolderPath(src, dst);
  }
  if (folder) { openFolders.add(folder); store.set('openFolders', [...openFolders]); }
  saveDB(); renderTree();
}

// ── 메뉴 ─────────────────────────────────────────────
function sessionMenu(s, x, y) {
  if (s.shared) {
    return showMenu(x, y, [
      { label: s.type === 'rdp' ? '원격 데스크톱 열기' : '접속', hint: '더블클릭', action: () => openSpec(s) },
      { label: '내 세션으로 복사…', action: () => { const c = JSON.parse(JSON.stringify(s)); delete c.shared; c.id = uid(); c.folder = (s.folder || '').replace(/^공유\/?/, ''); editSession(null, '', c); } },
      { label: '공유 세션 파일 (읽기 전용)', disabled: true, action() {} },
    ]);
  }
  showMenu(x, y, [
    { label: s.type === 'rdp' ? '원격 데스크톱 열기' : '접속', hint: '더블클릭', action: () => openSpec(s) },
    { label: '편집…', hint: 'F2', action: () => editSession(s) },
    { label: '복제', action: () => duplicateSession(s) },
    CAPS.local ? { label: '바탕화면 바로가기 만들기', action: () => makeShortcut(s) } : null,
    s.log ? { label: '로그 폴더 열기', action: () => api.call('openLogs', { name: s.name || s.host }).catch((e) => toast(e.message)) } : null,
    s.type === 'rdp' && VAULT && featureOn('passwordSave') ? { label: 'RDP 비밀번호 저장…', action: () => saveRdpPassword(s) } : null,
    vaultHas(s) || (s.type === 'rdp' && VAULT?.keys?.includes('rdp:' + credKey({ ...s, port: s.port || 3389 })))
      ? { label: '저장된 비밀번호 지우기', action: () => forgetSaved(s) } : null,
    '-',
    { label: '삭제', hint: 'Del', danger: true, action: () => deleteSession(s) },
  ]);
}
function folderMenu(f, x, y) {
  showMenu(x, y, [
    { label: '이 폴더 세션 모두 열기', hint: `${sessionsUnder(f).length}개`, action: () => openAllIn(f) },
    { label: '이 폴더에 새 세션', action: () => editSession(null, f) },
    { label: '하위 폴더 만들기', action: () => newFolder(f) },
    { label: '이름 바꾸기', action: () => renameFolder(f) },
    '-',
    { label: '폴더 삭제', danger: true, action: () => deleteFolder(f) },
  ]);
}

const sessionsUnder = (f) => allSessions().filter((s) => (s.folder || '') === f || (s.folder || '').startsWith(f + '/'))
  .filter((s) => s.type !== 'rdp' && featureOn(s.type === 'ssh' ? 'ssh' : s.type));
// 폴더의 세션 모두 실행 — 비밀번호는 하나씩 물음(같은 서버는 한 번만)
function openAllIn(f) {
  const list = sessionsUnder(f);
  if (!list.length) return toast('열 수 있는 세션이 없습니다');
  if (list.length > 6 && !confirm(`"${f}" 아래 세션 ${list.length}개를 모두 엽니다. 계속할까요?`)) return;
  list.forEach((s) => openSpec(s));
}

function newFolder(parent) {
  const name = prompt('새 폴더 이름');
  if (!name) return;
  const path = (parent ? parent + '/' : '') + name.replace(/\//g, '／').trim();
  if (allFolders().includes(path)) return toast('이미 있는 폴더입니다');
  DB.folders = [...(DB.folders || []), path];
  if (parent) openFolders.add(parent);
  openFolders.add(path);
  store.set('openFolders', [...openFolders]);
  saveDB(); renderTree();
}
function renameFolderPath(src, dst) {
  const swap = (p) => (p === src ? dst : p.startsWith(src + '/') ? dst + p.slice(src.length) : p);
  DB.folders = (DB.folders || []).map(swap);
  DB.sessions.forEach((s) => { if (s.folder) s.folder = swap(s.folder); });
  openFolders = new Set([...openFolders].map(swap));
  store.set('openFolders', [...openFolders]);
}
function renameFolder(f) {
  const name = prompt('새 이름', f.split('/').pop());
  if (!name) return;
  const dst = f.split('/').slice(0, -1).concat(name.replace(/\//g, '／').trim()).join('/');
  if (dst === f) return;
  if (allFolders().includes(dst)) return toast('이미 있는 폴더입니다');
  renameFolderPath(f, dst);
  saveDB(); renderTree();
}
function deleteFolder(f) {
  const inside = DB.sessions.filter((s) => s.folder === f || (s.folder || '').startsWith(f + '/'));
  if (!confirm(inside.length ? `"${f}" 폴더와 안의 세션 ${inside.length}개를 삭제할까요?` : `"${f}" 폴더를 삭제할까요?`)) return;
  DB.sessions = DB.sessions.filter((s) => !inside.includes(s));
  DB.folders = (DB.folders || []).filter((x) => x !== f && !x.startsWith(f + '/'));
  saveDB(); renderTree();
}
function deleteSession(s) {
  if (!confirm(`세션 "${sessName(s)}"을(를) 삭제할까요?`)) return;
  DB.sessions = DB.sessions.filter((x) => x !== s);
  saveDB(); renderTree(); renderRecent();
}
function duplicateSession(s) {
  const c = JSON.parse(JSON.stringify(s));
  c.id = uid();
  c.name = sessName(s) + ' (복사)';
  DB.sessions.push(c);
  saveDB(); renderTree();
  editSession(c);
}

// ── 세션 편집 대화상자 ───────────────────────────────────
function newSession() {
  const folder = treeSel?.kind === 'folder' ? treeSel.path : treeSel?.kind === 'session' ? findSession(treeSel.id)?.folder || '' : '';
  editSession(null, folder);
}
$('#tbSession').onclick = newSession;
$('#treeNewSession').onclick = newSession;
$('#homeNew').onclick = newSession;
$('#treeNewFolder').onclick = () => newFolder(treeSel?.kind === 'folder' ? treeSel.path : '');

const sForm = $('#sessionForm');
const DEFAULT_PORT = { ssh: 22, sftp: 22, mosh: 22, rdp: 3389, telnet: 23, rlogin: 513, ftp: 21, vnc: 5900 };
const NEEDS_USER = new Set(['ssh', 'sftp', 'mosh', 'rlogin', 'ftp']);
function syncSessionForm() {
  const type = sForm.stype.value;
  sForm.dataset.type = type;
  $$('[data-for]', sForm).forEach((el) => { el.hidden = !el.dataset.for.split(' ').includes(type); });
  sForm.port.placeholder = DEFAULT_PORT[type] || '';
  sForm.ftpInsecure.closest('label').hidden = type !== 'ftp' || sForm.ftpTls.value !== 'explicit';
  sForm.querySelector('.keyfile-row').hidden = sForm.auth.value !== 'keyfile';
  sForm.querySelector('.j-keyfile-row').hidden = sForm.j_auth.value !== 'keyfile' || !!sForm.jumpVia.value;
  $$('.j-manual', sForm).forEach((el) => { el.hidden = !!sForm.jumpVia.value; });
  $('#sdConnect').textContent = type === 'rdp' ? '저장하고 열기' : '저장하고 접속';
}
sForm.addEventListener('change', syncSessionForm);
$$('.pick', sForm).forEach((b) => {
  b.onclick = async () => {
    if (!CAPS.local) return toast('파일 선택창은 서버가 127.0.0.1로 실행 중일 때만 됩니다');
    b.disabled = true;
    try { const r = await api.call('pickFile'); if (r.path) sForm[b.dataset.forInput].value = r.path; }
    catch (e) { toast(e.message, 3000); }
    finally { b.disabled = false; }
  };
});
async function fillComPorts(cur) {
  let list = CAPS.com || [];
  try { list = (await api.call('comPorts')).ports; } catch {}
  sForm.com.innerHTML = (list.length ? list : ['(COM 포트 없음)']).map((c) => `<option>${escapeHtml(c)}</option>`).join('');
  if (cur && !list.includes(cur)) sForm.com.insertAdjacentHTML('afterbegin', `<option>${escapeHtml(cur)}</option>`);
  sForm.com.value = cur || list[0] || '';
}
$('#comRefresh').onclick = () => fillComPorts(sForm.com.value);

/** s=null 이면 새 세션. preset: 빠른 접속 탭을 저장할 때 등 */
async function editSession(s, folder = '', preset = null) {
  const src = s || preset || {};
  const isNew = !s;
  const f = sForm;
  $('#sdTitle').textContent = isNew ? '새 세션' : '세션 편집';
  f.stype.value = src.type || 'ssh';
  f.name.value = src.name || '';
  f.color.value = src.color || '';
  f.folder.value = s ? s.folder || '' : src.folder ?? folder;
  f.host.value = src.host || '';
  f.port.value = src.port && +src.port !== DEFAULT_PORT[src.type || 'ssh'] ? src.port : '';
  f.username.value = src.username || '';
  f.auth.value = src.auth === 'keyfile' ? 'keyfile' : 'password';
  f.keyPath.value = src.keyPath || '';
  f.encoding.value = f.encoding2.value = src.encoding || 'utf-8';
  f.log.checked = src.log ?? !!SETTINGS.logDefault;
  f.reconnect.checked = src.reconnect !== false;
  const j = src.jump || {};
  f.jumpVia.replaceChildren(new Option('(직접 입력 ↓)', ''), ...allSessions().filter((x) => x.type === 'ssh' && x.id !== src.id)
    .map((x) => new Option(`${sessName(x)} — ${targetStr(x)}${x.jumpVia || x.jump?.host ? ' (경유)' : ''}`, x.id)));
  f.jumpVia.value = src.jumpVia || '';
  f.querySelector('details.jump').open = !!(j.host || src.jumpVia);
  f.j_host.value = j.host || '';
  f.j_port.value = j.port && +j.port !== 22 ? j.port : '';
  f.j_username.value = j.username || '';
  f.j_auth.value = j.auth === 'keyfile' ? 'keyfile' : 'password';
  f.j_keyPath.value = j.keyPath || '';
  // 고급
  f.loginCmd.value = src.loginCmd || '';
  f.loginMacro.replaceChildren(new Option('(없음)', ''), ...(DB.macros || []).map((m) => new Option(m.name, m.id)));
  f.loginMacro.value = src.loginMacro || '';
  f.keepalive.value = src.keepalive || '';
  f.proxyType.value = src.proxy?.type || '';
  f.proxyHost.value = src.proxy?.host || '';
  f.proxyPort.value = src.proxy?.port || '';
  f.antiIdle.value = src.antiIdle || '';
  f.scrollback.value = src.scrollback || '';
  f.compress.checked = !!src.compress;
  f.agent.checked = !!src.agent;
  f.x11.checked = !!src.x11;
  f.querySelectorAll('details.jump')[1].open = !!(src.loginCmd || src.loginMacro || src.compress || src.agent || src.x11 || src.keepalive || src.scrollback || src.proxy || src.antiIdle);
  // Serial
  await fillComPorts(src.com);
  f.baud.value = String(src.baud || 9600);
  f.bits.value = String(src.bits || 8);
  f.parity.value = src.parity || 'N';
  f.stop.value = String(src.stop || 1);
  f.flow.value = src.flow || 'none';
  f.crlf.checked = !!src.crlf;
  // FTP / VNC
  f.ftpTls.value = src.ftpTls || '';
  f.ftpInsecure.checked = !!src.ftpInsecure;
  f.passive.checked = src.passive !== false;
  f.viewOnly.checked = !!src.viewOnly;
  f.vncScale.value = src.vncScale || 'fit';
  // RDP
  f.screen.value = src.screen || 'full';
  f.rdpMode.value = src.rdpMode || 'mstsc';
  f.gateway.replaceChildren(new Option('(직접 접속)', ''), ...allSessions().filter((x) => x.type === 'ssh' && x.id !== src.id)
    .map((x) => new Option(`${sessName(x)} — ${targetStr(x)}`, x.id)));
  f.gateway.value = src.gateway || '';
  f.clipboard.checked = src.clipboard !== false;
  f.drives.checked = !!src.drives;
  f.multimon.checked = !!src.multimon;
  f.admin.checked = !!src.admin;
  f.shell.replaceChildren(...(CAPS.shells.length ? CAPS.shells.map((x) => new Option(x.name, x.id)) : [new Option('(사용 가능한 셸 없음)', '')]));
  f.shell.value = src.shell || CAPS.shells[0]?.id || '';
  $('#sdError').textContent = '';
  syncSessionForm();

  for (;;) {
    const r = await dialogResult($('#sessionDlg'));
    if (r !== 'save' && r !== 'connect') return null;
    const type = f.stype.value;
    const v = { id: s?.id || uid(), type, name: f.name.value.trim(), folder: f.folder.value.trim().replace(/^\/+|\/+$/g, '') };
    if (f.color.value) v.color = f.color.value;
    if (type !== 'local' && type !== 'serial') {
      const host = f.host.value.trim();
      const tgt = parseTarget(host);                     // user@host:port 를 호스트 칸에 붙여넣어도 됨
      Object.assign(v, tgt ? { host: tgt.host, port: tgt.port === 22 ? DEFAULT_PORT[type] : tgt.port, username: tgt.username }
        : { host, port: +f.port.value || DEFAULT_PORT[type], username: type === 'vnc' ? '' : f.username.value.trim() });
    }
    if (['ssh', 'sftp', 'mosh'].includes(type)) {
      Object.assign(v, { auth: f.auth.value, keyPath: f.keyPath.value.trim(), encoding: f.encoding.value, jump: null });
      if (type !== 'sftp') Object.assign(v, { log: f.log.checked, reconnect: f.reconnect.checked });
      if (type !== 'mosh' && f.jumpVia.value) v.jumpVia = f.jumpVia.value;
      else if (type !== 'mosh' && f.j_host.value.trim()) {
        v.jump = { host: f.j_host.value.trim(), port: +f.j_port.value || 22, username: f.j_username.value.trim(),
                   auth: f.j_auth.value, keyPath: f.j_keyPath.value.trim() };
      }
      if (type === 'ssh') {
        const opt = { loginCmd: f.loginCmd.value.trim(), loginMacro: f.loginMacro.value, keepalive: +f.keepalive.value || 0,
                      scrollback: +f.scrollback.value || 0, compress: f.compress.checked, agent: f.agent.checked, x11: f.x11.checked,
                      antiIdle: +f.antiIdle.value || 0 };
        for (const [k, x] of Object.entries(opt)) if (x) v[k] = x;
        if (f.proxyType.value && f.proxyHost.value.trim()) {
          v.proxy = { type: f.proxyType.value, host: f.proxyHost.value.trim(), port: +f.proxyPort.value || (f.proxyType.value === 'http' ? 8080 : 1080) };
        }
      }
    } else if (type === 'telnet' || type === 'rlogin') {
      Object.assign(v, { encoding: f.encoding2.value, log: f.log.checked, reconnect: f.reconnect.checked });
      if (type === 'telnet' && f.gateway.value) v.gateway = f.gateway.value;
    } else if (type === 'serial') {
      Object.assign(v, { com: f.com.value, baud: +f.baud.value, bits: +f.bits.value, parity: f.parity.value, stop: +f.stop.value,
                         flow: f.flow.value, crlf: f.crlf.checked, encoding: f.encoding2.value, log: f.log.checked });
    } else if (type === 'ftp') {
      Object.assign(v, { ftpTls: f.ftpTls.value, ftpInsecure: f.ftpInsecure.checked, passive: f.passive.checked });
    } else if (type === 'vnc') {
      Object.assign(v, { viewOnly: f.viewOnly.checked, vncScale: f.vncScale.value });
      if (f.gateway.value) v.gateway = f.gateway.value;
    } else if (type === 'rdp') {
      Object.assign(v, { screen: f.screen.value, rdpMode: f.rdpMode.value, gateway: f.gateway.value, clipboard: f.clipboard.checked,
                         drives: f.drives.checked, multimon: f.multimon.checked, admin: f.admin.checked });
    } else {
      v.shell = f.shell.value;
    }
    const err = !['local', 'serial'].includes(type) && !v.host ? '호스트를 입력하세요'
      : NEEDS_USER.has(type) && !v.username ? '사용자를 입력하세요'
      : ['ssh', 'sftp', 'mosh'].includes(type) && v.auth === 'keyfile' && !v.keyPath ? '개인키 파일 경로를 입력하세요'
      : v.jump && !v.jump.username ? '점프 호스트 사용자를 입력하세요'
      : type === 'serial' && !/^COM\d+$/i.test(v.com || '') ? 'COM 포트를 고르세요'
      : type === 'local' && !v.shell ? '사용할 수 있는 셸이 없습니다' : '';
    if (err) { $('#sdError').textContent = err; continue; }

    if (s) Object.keys(s).forEach((k) => delete s[k]);
    const obj = Object.assign(s || {}, v);
    if (!DB.sessions.includes(obj)) DB.sessions.push(obj);
    if (v.folder) {
      v.folder.split('/').forEach((_, i, a) => openFolders.add(a.slice(0, i + 1).join('/')));
      store.set('openFolders', [...openFolders]);
    }
    await saveDB();
    renderTree();
    selectTree({ kind: 'session', id: obj.id });
    tabs.filter((t) => t.spec === obj).forEach((t) => { applyTabColor(t); refreshTabLabel(t); });
    if (r === 'connect') openSpec(obj);
    return obj;
  }
}

async function saveQuickAsSession(t) {
  const obj = await editSession(null, '', { ...t.spec, quick: false });
  if (obj) {
    t.spec = obj;
    t.tab.querySelector('.label').textContent = tabLabel(t);
    renderSessionChrome(t);
  }
}

// ── 최근 접속 / 홈 ───────────────────────────────────────
function renderRecent() {
  const ul = $('#recentList');
  ul.innerHTML = '';
  const items = store.get('recent', []).map(findSession).filter(Boolean).slice(0, 8);
  if (!items.length) { ul.innerHTML = '<li class="dim">아직 없음</li>'; return; }
  for (const s of items) {
    const li = document.createElement('li');
    li.innerHTML = `<span class="ic"></span><b></b><span class="dim"></span>`;
    li.querySelector('.ic').textContent = ICON[s.type];
    li.querySelector('b').textContent = sessName(s);
    li.querySelector('.dim').textContent = sessSub(s);
    li.onclick = () => openSpec(s);
    ul.appendChild(li);
  }
}

// ── 세션 파일 가져오기 ──────────────────────────────
// .ini 또는 내보낸 .mxtsessions 의 [Bookmarks*] 섹션 (비밀번호는 가져오지 않음)
function parseSessionIni(text) {
  const out = { folders: new Set(), sessions: [], skipped: 0 };
  let sec = null, folder = '';
  for (const line of text.split(/\r?\n/)) {
    const h = line.match(/^\[(.+)\]\s*$/);
    if (h) { sec = h[1]; folder = ''; continue; }
    if (!sec || !/^Bookmarks(_\d+)?$/.test(sec)) continue;
    if (line.startsWith('SubRep=')) {
      folder = line.slice(7).trim().replace(/\\/g, '/');
      if (folder) out.folders.add(folder);
      continue;
    }
    if (line.startsWith('ImgNum=')) continue;
    const eq = line.indexOf('=');
    if (eq < 0) continue;
    const name = line.slice(0, eq).trim(), m = line.slice(eq + 1).match(/^#(\d+)#(.*)$/);
    if (!m) continue;
    const f = m[2].split('#')[0].split('%').map((x) => x.trim());
    if (m[1] === '109' && f[1]) {               // SSH: 1=host 2=port 3=user 7=gateway host 8=gateway user 9=gateway port 14=key
      const key = (f[14] || '').replace(/^_ProfileDir_/i, '%USERPROFILE%');
      out.sessions.push({
        id: uid(), type: 'ssh', name, folder, host: f[1], port: +f[2] || 22, username: f[3] || '',
        auth: key ? 'keyfile' : 'password', keyPath: key, encoding: 'utf-8', log: !!SETTINGS.logDefault, reconnect: true,
        jump: f[7] ? { host: f[7], port: +f[9] || 22, username: f[8] || '', auth: 'password', keyPath: '' } : null,
      });
    } else if (m[1] === '91' && f[1]) {          // RDP: 1=host 2=port 3=user
      out.sessions.push({ id: uid(), type: 'rdp', name, folder, host: f[1], port: +f[2] || 3389, username: f[3] || '',
                          screen: 'full', gateway: '', clipboard: true });
    } else out.skipped++;
  }
  return out;
}

// 이 프로그램에서 내보낸 JSON 다시 가져오기 (같은 id는 건너뜀)
async function importJson(name, text) {
  let d;
  try { d = JSON.parse(text); } catch { return toast('JSON 형식이 아닙니다', 3000); }
  if (d.app !== 'webssh' || !Array.isArray(d.sessions)) return toast('이 프로그램에서 내보낸 파일이 아닙니다', 3000);
  const ids = new Set(DB.sessions.map((x) => x.id)), tids = new Set((DB.tunnels || []).map((x) => x.id));
  const add = d.sessions.filter((x) => x && x.id && !ids.has(x.id));
  const addT = (d.tunnels || []).filter((x) => x && x.id && !tids.has(x.id));
  if (!confirm(`${name}
세션 ${add.length}개, 터널 ${addT.length}개를 추가합니다 (이미 있는 것은 건너뜀). 계속할까요?`)) return;
  DB.sessions.push(...add);
  DB.tunnels = [...(DB.tunnels || []), ...addT];
  DB.folders = [...new Set([...(DB.folders || []), ...(d.folders || [])])];
  await saveDB();
  renderTree(); renderTunnels();
  toast(`세션 ${add.length}개 가져옴`, 2500);
}

$('#treeImport').onclick = () => {
  toast('세션 파일 가져오기 (.mxtsessions / .ini / .json)', 2500);
  $('#importFile').click();
};
$('#importFile').onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  const buf = await file.arrayBuffer();
  let text;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(buf); }
  catch { text = new TextDecoder('euc-kr').decode(buf); }       // ANSI(cp949)로 저장한 세션 파일도 지원
  if (/\.json$/i.test(file.name)) return importJson(file.name, text);
  const r = parseSessionIni(text);
  if (!r.sessions.length) return toast('가져올 SSH/RDP 세션을 찾지 못했습니다', 3000);
  const key = (s) => [s.type, s.host, s.port, s.username, s.folder].join('|');
  const have = new Set(DB.sessions.map(key));
  const add = r.sessions.filter((s) => !have.has(key(s)));
  const usersMissing = add.filter((s) => s.type === 'ssh' && !s.username).length;
  if (!confirm(`${file.name}\nSSH ${r.sessions.filter((s) => s.type === 'ssh').length}개, RDP ${r.sessions.filter((s) => s.type === 'rdp').length}개를 찾았습니다.\n` +
               `새로 추가: ${add.length}개 (이미 있는 ${r.sessions.length - add.length}개는 건너뜀)` +
               (r.skipped ? `\n지원하지 않는 종류 ${r.skipped}개는 제외` : '') +
               (usersMissing ? `\n※ 사용자 이름이 없는 세션 ${usersMissing}개는 접속 전에 편집에서 입력하세요.` : '') +
               '\n\n비밀번호는 가져오지 않습니다. 계속할까요?')) return;
  DB.sessions.push(...add);
  DB.folders = [...new Set([...(DB.folders || []), ...r.folders])];
  await saveDB();
  renderTree();
  toast(`${add.length}개 세션을 가져왔습니다`, 2500);
};

// 이전 버전(브라우저에 저장된 접속 목록) 옮기기
function migrateOldProfiles() {
  const old = store.get('profiles', []);
  if (!old.length || store.get('migratedProfiles', false)) return false;
  for (const p of old) {
    if (DB.sessions.some((s) => s.host === p.host && s.username === p.username && (s.port || 22) === (p.port || 22))) continue;
    DB.sessions.push({
      id: uid(), type: 'ssh', name: p.name || '', folder: '이전 접속 기록', host: p.host, port: p.port || 22, username: p.username,
      auth: 'password', keyPath: '', encoding: p.encoding || 'utf-8', log: !!SETTINGS.logDefault, reconnect: true,
      jump: p.jump ? { ...p.jump, auth: 'password', keyPath: '' } : null,
    });
  }
  store.set('migratedProfiles', true);
  return true;
}

// ── 설정 ─────────────────────────────────────────────
// 기능 표시: 끈 기능은 툴바·메뉴·세션 종류에서 숨김 (data-feature="키")
const FEATURES = {
  split: '화면 분할', multiexec: 'MultiExec', macro: '매크로', tunnels: 'SSH 터널', local: '로컬 터미널',
  passwordSave: '비밀번호 저장', rdp: 'RDP', telnet: 'Telnet', serial: 'Serial(COM)', sftp: 'SFTP 세션', ftp: 'FTP', vnc: 'VNC', mosh: 'Mosh',
  rlogin: 'Rlogin', x11: 'X11', tools: '도구 메뉴', logs: '로그 버튼',
};
const featureOn = (k) => !(SETTINGS.hiddenFeatures || []).includes(k);
function applyFeatures() {
  $$('[data-feature]').forEach((el) => el.classList.toggle('feat-off', !featureOn(el.dataset.feature)));
}
function applySettings(s) {
  SETTINGS = s;
  savedFontFamily = s.fontFamily || '';
  terminalFontReady = true;
  syncFontFamily();
  compileHighlight(s.highlight);
  tabs.forEach((t) => t.hl.reset());
  applyFeatures();
  renderStatus();
}
function hlRow(r = { pattern: '', color: '#ff6b6b', on: true }) {
  const row = document.createElement('div');
  row.className = 'hl-row';
  row.innerHTML = `<input type="checkbox" class="on"><input class="pat mono" spellcheck="false" placeholder="정규식 예: \\bfail\\w*"><input type="color" class="col"><button type="button" title="삭제">✕</button>`;
  row.querySelector('.on').checked = r.on !== false;
  row.querySelector('.pat').value = r.pattern;
  row.querySelector('.col').value = r.color;
  row.querySelector('button').onclick = () => row.remove();
  $('#hlRules').appendChild(row);
}
$('#hlAdd').onclick = () => hlRow();
// 툴바 ☀/☾: 라이트 ↔ 다크 바로 전환
$('#themeBtn').onclick = () => {
  store.set('uiTheme', currentUi() === 'dark' ? 'light' : 'dark');
  applyTheme();
};
$('#shutdownBtn').onclick = async () => {
  const running = Object.values(TUNNEL_STATUS).filter((s) => s.state !== 'off').length;
  const live = tabs.filter((t) => t.state === 'on').length;
  if (!confirm(`중계 서버를 종료할까요?${live ? `\n열린 접속 ${live}개가 끊깁니다.` : ''}${running ? `\n실행 중인 터널 ${running}개도 멈춥니다.` : ''}`)) return;
  $('#settingsDlg').close();
  api.stopped = true;          // 이후 끊김은 자동 재접속하지 않음
  try { await api.call('shutdown'); } catch {}
};
$('#tbSettings').onclick = async () => {
  await fontSaveQueue;
  const dlg = $('#settingsDlg'), f = dlg.querySelector('form');
  f.logDir.value = SETTINGS.logDir || '';
  f.logDir.placeholder = LOGDIR;
  f.logDefault.checked = !!SETTINGS.logDefault;
  f.monitor.checked = !!SETTINGS.monitor;
  f.followFolder.checked = SETTINGS.followFolder !== false;
  f.logTimestamp.checked = !!SETTINGS.logTimestamp;
  $('#vaultInfo').textContent = !VAULT ? '사용할 수 없음 (외부 바인딩)' : VAULT.locked ? '잠김 (마스터 비밀번호)' : `저장된 비밀번호 ${VAULT.keys.length}개${VAULT.master ? ' · 마스터 비밀번호 사용' : ''}`;
  $('#vaultBtn').onclick = () => { $('#settingsDlg').close('cancel'); setTimeout(vaultDialog, 50); };
  f.pasteWarn.checked = SETTINGS.pasteWarn !== false;
  f.globalHotkey.checked = !!SETTINGS.globalHotkey;
  f.sharedPath.value = SETTINGS.sharedPath || '';
  f.fontFamily.value = SETTINGS.fontFamily || '';
  syncUiFontSettings();
  f.scrollback.value = SETTINGS.scrollback || '';
  $('#featureChecks').innerHTML = Object.entries(FEATURES).map(([k, v]) =>
    `<label><input type="checkbox" data-k="${k}"${featureOn(k) ? ' checked' : ''}> ${escapeHtml(v)}</label>`).join('');
  $('#hlRules').innerHTML = '';
  (SETTINGS.highlight || []).forEach(hlRow);
  // 화면 테마 (브라우저별 저장, 고르면 바로 미리보기)
  const ui0 = uiThemeSetting(), term0 = store.get('termScheme', 'auto');
  const uiFont0 = uiFontFamilySetting(), uiSize0 = uiFontSizeSetting();
  f.uiFontFamily.onchange = () => setUiFontFamily(f.uiFontFamily.value);
  f.uiFontSize.onchange = () => setUiFontSize(f.uiFontSize.value);
  f.uiTheme.innerHTML = Object.entries(UI_THEMES).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
  f.termScheme.innerHTML = '<option value="auto">화면 테마에 맞춤</option>' +
    Object.entries(TERM_SCHEMES).map(([k, v]) => `<option value="${k}">${escapeHtml(v.name)}</option>`).join('');
  f.uiTheme.value = ui0;
  f.termScheme.value = term0;
  const preview = () => {
    applyTheme(f.uiTheme.value, f.termScheme.value);
    const t = TERM_SCHEMES[schemeKey(f.termScheme.value, currentUi(f.uiTheme.value))];
    const el = $('#schemePreview');
    el.style.background = t.background;
    el.style.color = t.foreground;
    const span = (txt, col) => `<span style="color:${col}">${txt}</span>`;
    el.innerHTML = `${span('root@web01', t.green)}:${span('~/app', t.blue)}# systemctl status nginx
` +
      `● nginx.service ${span('active (running)', adaptHighlight('#56d364'))}  ${span('192.0.2.150', adaptHighlight('#79c0ff'))}
` +
      `${span('error', adaptHighlight('#ff6b6b'))}: connection ${span('refused', adaptHighlight('#ff6b6b'))} · ${span('warning', adaptHighlight('#e3b341'))}: disk 85%  ` +
      ['red', 'green', 'yellow', 'blue', 'magenta', 'cyan'].map((k) => span('■', t[k])).join('');
  };
  f.uiTheme.onchange = f.termScheme.onchange = preview;
  preview();
  let highlight;
  for (;;) {                          // 정규식이 틀리면 고친 내용 그대로 다시 띄움
    if ((await dialogResult(dlg)) !== 'save') {
      applyTheme(ui0, term0);
      setUiFontFamily(uiFont0);
      setUiFontSize(uiSize0);
      return;
    }
    const rows = $$('.hl-row', dlg).filter((r) => r.querySelector('.pat').value.trim());
    const bad = rows.find((r) => { try { new RegExp(r.querySelector('.pat').value.trim()); return false; } catch { return true; } });
    if (!bad) {
      highlight = rows.map((r) => ({
        pattern: r.querySelector('.pat').value.trim(), color: r.querySelector('.col').value, on: r.querySelector('.on').checked,
      }));
      break;
    }
    toast(`잘못된 정규식: ${bad.querySelector('.pat').value.trim()}`, 3500);
    setTimeout(() => bad.querySelector('.pat').focus());
  }
  store.set('uiTheme', f.uiTheme.value);
  store.set('termScheme', f.termScheme.value);
  const uiSize = f.uiFontSize.value, uiFamily = f.uiFontFamily.value;
  setUiFontSize(uiSize);
  setUiFontFamily(uiFamily);
  applyTheme();
  const next = { ...SETTINGS, logDir: f.logDir.value.trim(), logDefault: f.logDefault.checked, monitor: f.monitor.checked,
                 followFolder: f.followFolder.checked, highlight, logTimestamp: f.logTimestamp.checked,
                 pasteWarn: f.pasteWarn.checked, globalHotkey: f.globalHotkey.checked, sharedPath: f.sharedPath.value.trim(), fontFamily: f.fontFamily.value.trim(), scrollback: +f.scrollback.value || 0,
                 hiddenFeatures: $$('#featureChecks input').filter((i) => !i.checked).map((i) => i.dataset.k) };
  try {
    const r = await api.call('saveSettings', { settings: next });
    LOGDIR = r.logDir;
    const followChanged = (SETTINGS.followFolder !== false) !== (next.followFolder !== false);
    applySettings(next);
    syncMonitor();
    tabs.forEach((t) => {
      if (next.scrollback && !t.spec.scrollback) t.term.options.scrollback = next.scrollback;
    });
    if (followChanged) tabs.forEach((t) => t.sftp?.setFollow(next.followFolder !== false));
    toast('설정 저장됨', 1000);
  } catch (e) { toast('저장 실패: ' + e.message, 3000); }
};

// ── 시작 ─────────────────────────────────────────────
async function loadAll() {
  const r = await api.call('load');
  DB = r.data;
  CAPS = r.caps;
  SHARED = (r.shared || []).map((s) => ({ ...s, shared: true }));
  if (r.sharedError) toast('공유 세션 파일: ' + r.sharedError, 4000);
  capsReady();
  VAULT = r.vault;
  LOGDIR = r.logDir;
  applySettings(r.settings);
  setTunnelStatus(r.tunnels);
  if (migrateOldProfiles()) await saveDB();
  renderTree();
  renderTunnels();
  renderRecent();
  updateToolbar();
}

(async () => {
  api.connect();
  api.on('data', (m) => { DB = m.data; renderTree(); renderTunnels(); renderRecent(); });
  api.on('settings', (m) => applySettings(m.settings));
  api.onReopen = () => loadAll().catch(() => {});
  renderLayout();
  try { await loadAll(); }
  catch (e) { toast('서버에서 설정을 읽지 못했습니다: ' + e.message, 4000); }
  $('#sbText').textContent = '준비';
  openFromUrl();
})();

// ?open=<세션 id 또는 이름> (바탕화면 바로가기·--session·새 창으로 분리), ?quick=user@host:port, ?local=<셸>
function openFromUrl() {
  const q = new URLSearchParams(location.search);
  const id = q.get('open'), quick = q.get('quick'), local = q.get('local');
  if (id) {
    const s = findSession(id) || allSessions().find((x) => sessName(x) === id || x.name === id);
    if (s) openSpec(s); else toast(`세션을 찾을 수 없습니다: ${id}`, 3000);
  }
  if (quick) {
    const t = parseTarget(quick);
    if (t) openSpec({ id: 'q-' + uid(), type: 'ssh', quick: true, name: '', ...t, auth: 'password', encoding: 'utf-8', log: !!SETTINGS.logDefault, reconnect: true, jump: null });
  }
  if (local) { const sh = CAPS.shells.find((x) => x.id === local) || CAPS.shells[0]; if (sh) openSpec({ id: 'local-' + sh.id, type: 'local', shell: sh.id, name: sh.name, quick: true }); }
  if (id || quick || local) history.replaceState(null, '', location.pathname + (TOKEN ? '?t=' + encodeURIComponent(TOKEN) : ''));
}
// 탭을 새 창으로 분리: 새 앱 창이 같은 세션으로 다시 접속하고 이 탭은 닫음 (연결은 새로 맺음)
function detachTab(s) {
  const q = new URLSearchParams();
  if (TOKEN) q.set('t', TOKEN);
  if (!s.spec.quick && findSession(s.spec.id)) q.set('open', s.spec.id);
  else if (s.kind === 'ssh') q.set('quick', targetStr({ ...s.spec, port: s.spec.port || 22 }));
  else if (s.kind === 'local') q.set('local', s.spec.shell);
  else return toast('이 탭은 새 창으로 옮길 수 없습니다');
  const w = window.open(location.pathname + '?' + q, '_blank', 'popup,width=1100,height=720');
  if (!w) return toast('팝업이 막혀 있습니다');
  closeTab(s, true);
}
async function makeShortcut(s) {
  try { const r = await api.call('makeShortcut', { sid: s.id, name: sessName(s) }); toast(`바탕화면에 만듦: ${r.path}`, 3000); }
  catch (e) { toast('바로가기 만들기 실패: ' + e.message, 3500); }
}
