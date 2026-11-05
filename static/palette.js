'use strict';
/* 명령 팔레트 (Ctrl+Shift+P / F1): 저장된 세션·열린 탭·동작을 이름으로 찾아 바로 실행.
 * 다른 모듈은 paletteAction({...})으로 동작을 추가한다. */

const PALETTE_ACTIONS = [];
function paletteAction(a) { PALETTE_ACTIONS.push(a); }

[
  { label: '새 세션', hint: 'Ctrl+Shift+N', run: () => newSession() },
  { label: '빠른 접속', hint: 'Ctrl+Shift+Q', run: () => $('#quick').focus() },
  { label: '설정', run: () => $('#tbSettings').click() },
  { label: '화면 분할: 한 화면', hint: 'Ctrl+Alt+1', feature: 'split', run: () => setLayout('1') },
  { label: '화면 분할: 좌우 2분할', hint: 'Ctrl+Alt+2', feature: 'split', run: () => setLayout('2v') },
  { label: '화면 분할: 상하 2분할', hint: 'Ctrl+Alt+3', feature: 'split', run: () => setLayout('2h') },
  { label: '화면 분할: 4분할', hint: 'Ctrl+Alt+4', feature: 'split', run: () => setLayout('4') },
  { label: '사이드바 접기/펴기', hint: 'Ctrl+Shift+B', run: () => toggleSidebar() },
  { label: 'SFTP 탐색기 보기', hint: 'Ctrl+Alt+F', run: () => setSide('sftp') },
  { label: 'SSH 터널 보기', feature: 'tunnels', run: () => setSide('tunnels') },
  { label: '새 SSH 터널', feature: 'tunnels', run: () => { setSide('tunnels'); $('#tunnelAdd').click(); } },
  { label: '세션 로그 폴더 열기', feature: 'logs', run: () => $('#tbLogs').click() },
  { label: '전체화면', hint: 'F11', run: () => toggleFullscreen() },
  { label: '글자 크게', run: () => setFont(fontSize + 1) },
  { label: '글자 작게', run: () => setFont(fontSize - 1) },
  { label: '라이트/다크 전환', run: () => $('#themeBtn').click() },
  { label: '터미널에서 찾기', hint: 'Ctrl+Shift+F', tab: true, run: (s) => openFind(s) },
  { label: '다음 에러로 이동', tab: true, run: (s) => jumpError(s, 1) },
  { label: '출력 내용 저장', hint: 'Ctrl+Shift+S', tab: true, run: (s) => saveOutput(s) },
  { label: '출력 인쇄', tab: true, run: (s) => printOutput(s) },
  { label: '탭 이름 바꾸기', tab: true, run: (s) => renameTab(s) },
  { label: '탭 복제', hint: 'Ctrl+Shift+U', tab: true, run: (s) => openTab(s.spec) },
  { label: '재접속', tab: true, run: (s) => reconnectNow(s) },
  { label: '탭 닫기', hint: 'Ctrl+Alt+W', tab: true, run: (s) => closeTab(s) },
  { label: '터미널 화면 지우기', tab: true, run: (s) => s.term.clear() },
  { label: '화면 잠금', hint: 'Ctrl+Alt+L', run: () => lockScreen() },
  { label: '이 PC 파일 탐색기', run: () => openLocalFiles() },
  { label: '두 칸 파일 탐색기 (이 PC ↔ 현재 서버)', run: () => openLocalFiles(true) },
  { label: '세션 파일 가져오기 (.mxtsessions / .ini / .json)', run: () => $('#importFile').click() },
  { label: '세션 내보내기 (JSON)', run: () => exportSessions() },
].forEach(paletteAction);
CAPS_READY.then(() => {
  for (const sh of CAPS.shells) {
    paletteAction({ label: `로컬 터미널: ${sh.name}`, feature: 'local', kind: '▣',
                    run: () => openSpec({ id: 'local-' + sh.id, type: 'local', shell: sh.id, name: sh.name, quick: true }) });
  }
});

// 글자 순서대로 들어 있으면 매치(퍼지). 연속·단어 시작일수록 점수가 높음. 매치 위치도 돌려줌.
function fuzzy(q, text) {
  if (!q) return { score: 0, pos: [] };
  const t = text.toLowerCase();
  const direct = t.indexOf(q);
  if (direct >= 0) return { score: 1000 - direct * 2 - t.length * 0.1, pos: [...Array(q.length).keys()].map((k) => k + direct) };
  let ti = 0, score = 0, last = -2;
  const pos = [];
  for (const ch of q) {
    const i = t.indexOf(ch, ti);
    if (i < 0) return null;
    score += i === last + 1 ? 8 : /[\s/@._-]/.test(t[i - 1] || ' ') ? 6 : 1;
    pos.push(i);
    last = i; ti = i + 1;
  }
  return { score: score - t.length * 0.1, pos };
}
function markText(text, pos) {
  const set = new Set(pos);
  return [...text].map((c, i) => (set.has(i) ? `<mark>${escapeHtml(c)}</mark>` : escapeHtml(c))).join('');
}

function paletteItems(qRaw) {
  const actionsOnly = qRaw.startsWith('>');
  const q = (actionsOnly ? qRaw.slice(1) : qRaw).trim().toLowerCase();
  const f = focused();
  const out = [];
  if (!actionsOnly) {
    for (const t of tabs) {
      const text = `${tabLabel(t)}  ${t.kind === 'local' ? '' : targetStr(t.spec)}`;
      const m = fuzzy(q, text);
      if (m) out.push({ kind: '⇥', title: tabLabel(t), sub: '열린 탭으로 이동', m, text, boost: 30, run: () => show(t) });
    }
    for (const s of DB.sessions) {
      if (!featureOn(s.type === 'ssh' ? 'ssh' : s.type)) continue;
      const text = `${sessName(s)}  ${sessSub(s)}  ${s.folder || ''}`;
      const m = fuzzy(q, text);
      if (m) out.push({ kind: ICON[s.type] || 'SSH', title: sessName(s), sub: [sessSub(s), s.folder].filter(Boolean).join(' · '), m, text,
                        color: LABEL_COLORS[s.color]?.[1], boost: 20, run: () => openSpec(s) });
    }
  }
  if (featureOn('macro')) {
    for (const mc of DB.macros || []) {
      const label = `매크로 재생: ${mc.name}`, m = fuzzy(q, label);
      if (m) out.push({ kind: '▶', title: label, sub: `입력 ${mc.steps.length}개${ME.on ? ' → MultiExec 대상' : ''}`, m, text: label, boost: 5, run: () => playMacro(mc) });
    }
  }
  for (const a of PALETTE_ACTIONS) {
    if (a.feature && !featureOn(a.feature)) continue;
    if (a.tab && !f) continue;
    const m = fuzzy(q, a.label);
    if (m) out.push({ kind: a.kind || '›', title: a.label, hint: a.hint, m, text: a.label, boost: actionsOnly ? 40 : 0, run: () => a.run(f) });
  }
  out.sort((a, b) => (b.m.score + b.boost) - (a.m.score + a.boost));
  return out.slice(0, 60);
}

function openPalette(initial = '') {
  const dlg = $('#paletteDlg'), inp = dlg.querySelector('.pq'), list = dlg.querySelector('.pl');
  if (dlg.open) return;
  let items = [], sel = 0;
  const render = () => {
    items = paletteItems(inp.value);
    sel = Math.min(sel, Math.max(0, items.length - 1));
    list.innerHTML = '';
    items.forEach((it, i) => {
      const row = document.createElement('div');
      row.className = 'pi' + (i === sel ? ' on' : '');
      const titleEnd = it.title.length;
      const tPos = it.m.pos.filter((p) => p < titleEnd);
      row.innerHTML = `<span class="pk"></span><span class="pt">${markText(it.title, tPos)}</span><span class="ps"></span><span class="ph"></span>`;
      row.querySelector('.pk').textContent = it.kind;
      if (it.color) row.querySelector('.pk').style.cssText = `border-left:0.25rem solid ${it.color};`;
      row.querySelector('.ps').textContent = it.sub || '';
      row.querySelector('.ph').textContent = it.hint || '';
      row.onmousemove = () => { if (sel !== i) { sel = i; paint(); } };
      row.onclick = () => go(i);
      list.appendChild(row);
    });
    if (!items.length) list.innerHTML = '<div class="side-empty">일치하는 항목 없음</div>';
  };
  const paint = () => $$('.pi', list).forEach((r, i) => { r.classList.toggle('on', i === sel); if (i === sel) r.scrollIntoView({ block: 'nearest' }); });
  const go = (i, newTab) => {
    const it = items[i];
    if (!it) return;
    dlg.close();
    setTimeout(() => it.run(newTab), 0);
  };
  inp.oninput = () => { sel = 0; render(); };
  inp.onkeydown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); paint(); }
    else if (e.key === 'PageDown') { e.preventDefault(); sel = Math.min(items.length - 1, sel + 8); paint(); }
    else if (e.key === 'PageUp') { e.preventDefault(); sel = Math.max(0, sel - 8); paint(); }
    else if (e.key === 'Enter') { e.preventDefault(); go(sel, e.shiftKey); }
  };
  dlg.onclose = () => { if (!$('dialog[open]')) focused()?.term.focus(); };
  dlg.onclick = (e) => { if (e.target === dlg) dlg.close(); };      // 바깥(backdrop) 클릭 = 닫기
  inp.value = initial;
  render();
  dlg.showModal();
  inp.focus();
}
$('#tbPalette').onclick = () => openPalette();
$('#treeExport').onclick = () => exportSessions();
$('#sideToggle').onclick = () => toggleSidebar();

// 세션 내보내기 (비밀번호 없음)
function exportSessions() {
  const data = { app: 'webssh', version: 1, exported: new Date().toISOString(), folders: DB.folders || [], sessions: DB.sessions, tunnels: DB.tunnels || [] };
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' }));
  a.download = `webssh-sessions-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  toast(`세션 ${DB.sessions.length}개 내보냄 (비밀번호는 포함 안 됨)`, 2500);
}

// ── 비밀번호 저장소 관리 ─────────────────────────────────
async function saveRdpPassword(s) {
  if (!s.username) return toast('RDP 세션에 사용자 이름을 먼저 입력하세요 (세션 편집)', 3000);
  if (!(await unlockVault())) return;
  const v = await promptSecrets([{ which: 'rdp', key: 'password', label: `${s.username}@${s.host} 비밀번호` }], `RDP 비밀번호 저장 — ${sessName(s)}`, true);
  if (!v) return;
  try {
    VAULT = (await api.call('vaultSet', { key: 'rdp:' + credKey({ ...s, port: s.port || 3389 }), password: v['rdp.password'] })).vault;
    toast('저장됨 — 다음부터 원격 데스크톱이 비밀번호를 묻지 않습니다', 2500);
  } catch (e) { toast(e.message, 3000); }
}
async function forgetSaved(s) {
  const key = s.type === 'rdp' ? 'rdp:' + credKey({ ...s, port: s.port || 3389 }) : credKey(s);
  if (!confirm(`${key}의 저장된 비밀번호를 지울까요?`)) return;
  try { VAULT = (await api.call('vaultDelete', { key })).vault; SECRETS.delete(credKey(s)); toast('지움'); }
  catch (e) { toast(e.message, 3000); }
}
async function vaultDialog() {
  if (!VAULT) return toast('비밀번호 저장소는 서버가 127.0.0.1로 실행 중일 때만 쓸 수 있습니다', 3000);
  if (VAULT.locked && !(await unlockVault())) return;
  const keys = VAULT.keys;
  const x = $('#tbSettings').getBoundingClientRect();
  showMenu(x.left, x.bottom + 2, [
    { label: `저장된 비밀번호 ${keys.length}개`, disabled: true, action() {} },
    ...keys.slice(0, 30).map((k) => ({ label: `✕ ${k}`, hint: '지우기', action: async () => {
      if (confirm(`${k} 지울까요?`)) { VAULT = (await api.call('vaultDelete', { key: k })).vault; toast('지움'); }
    } })),
    '-',
    { label: VAULT.master ? '마스터 비밀번호 변경/해제…' : '마스터 비밀번호 설정…', action: setMasterPassword },
    VAULT.master ? { label: '지금 잠그기', action: async () => { VAULT = (await api.call('vaultLock')).vault; SECRETS.clear(); toast('잠금'); } } : null,
  ]);
}
async function setMasterPassword() {
  const fields = [];
  if (VAULT.master) fields.push({ which: 'm', key: 'old', label: '현재 마스터 비밀번호' });
  fields.push({ which: 'm', key: 'new', label: '새 마스터 비밀번호 (비우면 해제)' }, { which: 'm', key: 'new2', label: '새 마스터 비밀번호 확인' });
  const v = await promptSecrets(fields, '마스터 비밀번호', true);
  if (!v) return;
  if (v['m.new'] !== v['m.new2']) return toast('새 비밀번호가 서로 다릅니다', 2500);
  try {
    VAULT = (await api.call('vaultMaster', { old: v['m.old'] || null, new: v['m.new'] || '' })).vault;
    toast(v['m.new'] ? '마스터 비밀번호 설정됨 — 프로그램을 켤 때마다 한 번 입력합니다' : '마스터 비밀번호 해제됨', 3000);
  } catch (e) { toast(e.message, 3000); }
}
paletteAction({ label: '비밀번호 저장소 관리', feature: 'passwordSave', run: () => vaultDialog() });

// 이 PC 파일 탭. dual이면 좌우 분할 → 왼쪽 = 지금 서버의 SFTP(파일 전용 탭), 오른쪽 = 이 PC. 행을 끌어 서로 복사.
function openLocalFiles(dual) {
  if (!CAPS.local) return toast('이 PC 파일 탐색기는 서버가 127.0.0.1로 실행 중일 때만 됩니다', 3000);
  const f = focused();
  if (dual) {
    if (!f || f.kind !== 'ssh') return toast('먼저 SSH 탭을 여세요');
    setLayout('2v');
    openTab({ ...f.spec, type: 'sftp', quick: true, name: `${tabLabel(f)} 파일` });
  }
  openTab({ id: 'localfs', type: 'localfs', quick: true, name: '이 PC' });
}
