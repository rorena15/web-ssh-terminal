'use strict';
/* MultiExec (여러 탭에 같은 입력) + 매크로 (입력 녹화·재생).
 * MultiExec: 켜면 위쪽에 대상 탭 칩이 나오고, 대상 탭 하나에 친 키가 나머지 대상에도 그대로 간다.
 *            "한 줄 명령" 칸은 확인 후 Enter로 대상 전체에 한 번에 보낸다(프롬프트가 밀려 오타가 실행되는 것 방지).
 * 매크로: 녹화 중 현재 탭에 친 입력을 시간 간격과 함께 저장(data/sessions.json의 macros) → 아무 탭에서나 재생. */

const enc = new TextEncoder();
const ME = { on: false, targets: new Set(), relaying: false };

function toggleMultiExec(force) {
  ME.on = force ?? !ME.on;
  if (ME.on && !ME.targets.size) tabs.filter((t) => cells.includes(t)).forEach((t) => ME.targets.add(t.id));
  $('#tbMulti').classList.toggle('on', ME.on);
  renderMultiBar();
  paintMultiTargets();
  toast(ME.on ? 'MultiExec 켜짐 — 대상 탭 하나에 입력하면 나머지에도 같이 갑니다' : 'MultiExec 꺼짐', 2200);
}
$('#tbMulti').onclick = () => toggleMultiExec();

function paintMultiTargets() {
  const badge = $('#meBadge');
  badge.hidden = !ME.on;
  badge.textContent = 'MultiExec · ' + tabs.filter(t => ME.targets.has(t.id)).length;
  for (const t of tabs) {
    const on = ME.on && ME.targets.has(t.id);
    t.pane.classList.toggle('me-target', on);
    t.tab.classList.toggle('me-target', on);
    renderSessionChrome(t);
  }
}

function renderMultiBar() {
  let bar = $('#multiBar');
  if (!ME.on) { bar?.remove(); return; }
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'multiBar';
    bar.dataset.feature = 'multiexec';
    bar.classList.toggle('feat-off', !featureOn('multiexec'));
    bar.innerHTML = `<b>${uiIcon('multi')} MultiExec</b>
      <span class="me-chips"></span>
      <span class="me-quick">
        <button data-q="all" title="열린 탭 전부">전체</button><button data-q="visible" title="화면에 보이는 칸만">보이는 칸</button>
        <button data-q="noprod" title="빨강(운영) 라벨 세션 빼기">운영 제외</button><button data-q="none">선택 해제</button>
      </span>
      <input class="me-line mono" placeholder="한 줄 명령 → Enter = 대상 전체에 보내기" spellcheck="false">
      <button class="me-off" title="끄기 (Ctrl+Shift+M)">끄기</button>`;
    $('#right').insertBefore(bar, $('#workspace'));
    bar.querySelector('.me-off').onclick = () => toggleMultiExec(false);
    bar.querySelectorAll('[data-q]').forEach((b) => {
      b.onclick = () => {
        const q = b.dataset.q;
        ME.targets = new Set(tabs.filter((t) => q === 'all' || (q === 'visible' && cells.includes(t)) || (q === 'noprod' && t.spec.color !== 'red')).map((t) => t.id));
        renderMultiBar(); paintMultiTargets();
      };
    });
    const line = bar.querySelector('.me-line');
    line.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const cmd = line.value;
      const tgt = tabs.filter((t) => ME.targets.has(t.id) && isOpen(t));
      if (!tgt.length) return toast('보낼 대상 탭이 없습니다 (연결된 탭을 고르세요)');
      const prod = tgt.filter((t) => t.spec.color === 'red').length;
      if ((prod || DANGER_RE.test(cmd)) && !confirm(`${tgt.length}개 탭에 보냅니다${prod ? ` (운영 ${prod}개 포함)` : ''}:\n\n${cmd}\n\n계속할까요?`)) return;
      tgt.forEach((t) => sendInput(t, enc.encode(cmd + '\r')));
      line.value = '';
      toast(`${tgt.length}개 탭에 보냄`, 1200);
    });
  }
  const chips = bar.querySelector('.me-chips');
  chips.innerHTML = '';
  for (const t of tabs) {
    const c = document.createElement('label');
    c.className = 'me-chip' + (t.state === 'on' ? '' : ' off');
    if (t.spec.color) c.style.setProperty('--tc', LABEL_COLORS[t.spec.color]?.[1] || '');
    c.innerHTML = `<input type="checkbox"><span></span>`;
    c.querySelector('span').textContent = tabLabel(t);
    const cb = c.querySelector('input');
    cb.checked = ME.targets.has(t.id);
    cb.onchange = () => { cb.checked ? ME.targets.add(t.id) : ME.targets.delete(t.id); paintMultiTargets(); };
    chips.appendChild(c);
  }
}

// 대상 탭 하나에 친 키 → 다른 대상에도 (원래 탭에는 xterm이 이미 보냄)
inputHooks.push((s, d) => {
  if (!ME.on || ME.relaying || !ME.targets.has(s.id)) return;
  ME.relaying = true;
  try {
    for (const t of tabs) if (t !== s && ME.targets.has(t.id)) sendInput(t, enc.encode(d));
  } finally { ME.relaying = false; }
});

// 탭이 열리고 닫힐 때 칩 갱신
const _closeTab = closeTab;
closeTab = function (s, force) {
  _closeTab(s, force);
  if (!tabs.includes(s)) { ME.targets.delete(s.id); if (ME.on) renderMultiBar(); paintMultiTargets(); }
};
const _openTab = openTab;
openTab = function (spec) {
  const s = _openTab(spec);
  if (ME.on) { renderMultiBar(); paintMultiTargets(); }
  return s;
};

paletteAction({ label: 'MultiExec 켜기/끄기', hint: 'Ctrl+Shift+M', feature: 'multiexec', run: () => toggleMultiExec() });

// ── 매크로 ───────────────────────────────────────────────
const MACRO = { rec: null };      // rec: {tab, steps: [{w: ms, d: text}], last: time}

function macros() { return (DB.macros ||= []); }

function startRecording() {
  const s = focused();
  if (!s) return toast('녹화할 터미널 탭을 먼저 여세요');
  MACRO.rec = { tab: s, steps: [], last: performance.now() };
  $('#tbMacro').classList.add('rec');
  $('#tbMacro').title = '녹화 중 — 누르면 중지·저장';
  toast(`⏺ 녹화 시작 (${tabLabel(s)}) — 다시 누르면 저장`, 2500);
  s.term.focus();
}
async function stopRecording() {
  const r = MACRO.rec;
  MACRO.rec = null;
  $('#tbMacro').classList.remove('rec');
  $('#tbMacro').title = '매크로 녹화·재생';
  if (!r || !r.steps.length) return toast('녹화된 입력이 없습니다');
  const name = prompt(`매크로 이름 (입력 ${r.steps.length}개)`, `매크로 ${macros().length + 1}`);
  if (!name) return;
  macros().push({ id: uid(), name: name.trim(), steps: r.steps });
  await saveDB();
  toast(`매크로 "${name}" 저장됨`, 1800);
}
inputHooks.push((s, d) => {
  const r = MACRO.rec;
  if (!r || r.tab !== s || ME.relaying || r.playing) return;
  const now = performance.now();
  r.steps.push({ w: Math.min(5000, Math.round(now - r.last)), d });
  r.last = now;
});

// 재생: 대상 = 지정한 탭들 (기본: 현재 탭, MultiExec가 켜져 있으면 그 대상들)
async function playMacro(m, targets, fast) {
  targets = (targets || (ME.on ? tabs.filter((t) => ME.targets.has(t.id)) : [focused()])).filter((t) => t && isOpen(t));
  if (!targets.length) return toast('재생할 연결된 탭이 없습니다');
  if (targets.some((t) => t.spec.color === 'red') && !confirm(`운영(빨강) 세션이 포함되어 있습니다. "${m.name}"을(를) 재생할까요?`)) return;
  toast(`▶ ${m.name} → ${targets.length}개 탭`, 1500);
  for (const st of m.steps) {
    if (!fast && st.w > 20) await sleep(st.w);
    targets.forEach((t) => sendInput(t, enc.encode(st.d)));
  }
}

function macroMenu(x, y) {
  const list = macros();
  showMenu(x, y, [
    MACRO.rec ? { label: '녹화 중지·저장', action: stopRecording } : { label: '녹화 시작 (현재 탭)', action: startRecording },
    list.length ? '-' : null,
    ...list.map((m) => ({ label: m.name, hint: `${m.steps.length}`, action: () => playMacro(m) })),
    list.length ? '-' : null,
    list.length ? { label: '매크로 관리…', action: manageMacros } : null,
  ]);
}
$('#tbMacro').onclick = (e) => {
  if (MACRO.rec) return stopRecording();
  const r = e.currentTarget.getBoundingClientRect();
  macroMenu(r.left, r.bottom + 2);
};

function manageMacros() {
  const list = macros();
  const pick = prompt('관리할 매크로 번호:\n' + list.map((m, i) => `${i + 1}. ${m.name} (입력 ${m.steps.length}개)`).join('\n'));
  const m = list[+pick - 1];
  if (!m) return;
  const rect = $('#tbMacro').getBoundingClientRect();
  showMenu(rect.left, rect.bottom + 2, [
    { label: `"${m.name}" 빠르게 재생 (간격 무시)`, action: () => playMacro(m, null, true) },
    { label: '이름 바꾸기…', action: async () => { const n = prompt('새 이름', m.name); if (n) { m.name = n.trim(); await saveDB(); } } },
    { label: '내용 보기', action: () => alert(m.steps.map((s) => s.d).join('').replace(/\r/g, '⏎\n').slice(0, 2000)) },
    '-',
    { label: '삭제', danger: true, action: async () => { if (confirm(`"${m.name}" 삭제?`)) { DB.macros = list.filter((x) => x !== m); await saveDB(); } } },
  ]);
}

// 세션 설정의 "접속 후 실행": 명령(줄 단위) 또는 매크로
function runOnLogin(s) {
  const p = s.spec;                                 // 접속할 때마다(재접속 포함) 실행
  if (p.loginCmd) {
    const lines = p.loginCmd.replace(/\r\n/g, '\n').split('\n').filter((x) => x.trim());
    (async () => { await sleep(600); for (const l of lines) { sendInput(s, enc.encode(l + '\r')); await sleep(250); } })();
  }
  const m = p.loginMacro && macros().find((x) => x.id === p.loginMacro);
  if (m) setTimeout(() => playMacro(m, [s]), p.loginCmd ? 1500 : 600);
}

paletteAction({ label: '매크로 녹화 시작/중지', feature: 'macro', run: () => (MACRO.rec ? stopRecording() : startRecording()) });
