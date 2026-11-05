'use strict';
/* 터미널 부가 기능: 찾기·다음 에러, 붙여넣기 확인, 출력 저장/인쇄, 탭 이름·순서·색 라벨 */

// ── 터미널에서 찾기 (Ctrl+Shift+F, F3 / Shift+F3, 다음 에러) ─────────────
const FIND_BAR_HTML = `<div class="findbar" hidden>
  <input class="fq mono" placeholder="찾기 (Enter 다음 · Shift+Enter 이전)" spellcheck="false">
  <label class="fre" title="정규식"><input type="checkbox">.*</label>
  <span class="fn hint"></span>
  <button class="fprev" title="이전 (Shift+F3)">↑</button><button class="fnext" title="다음 (F3)">↓</button>
  <button class="ferr" title="다음 에러 (빨간 하이라이트 규칙)">⚠ 다음 에러</button>
  <button class="fx" title="닫기 (Esc)">✕</button></div>`;

// 한 줄의 문자열과 문자 위치 → 열 위치 대응 (한글 등 2칸 문자)
function lineCols(line) {
  let str = '';
  const col = [], wid = [];
  for (let x = 0; x < line.length; x++) {
    const c = line.getCell(x);
    const w = c.getWidth();
    if (w === 0) continue;
    const ch = c.getChars() || ' ';
    for (let i = 0; i < ch.length; i++) { col.push(x); wid.push(w); }
    str += ch;
  }
  return { str, col, wid };
}

function findMatches(s, re) {
  const b = s.term.buffer.active, out = [];
  for (let y = 0; y < b.length; y++) {
    const line = b.getLine(y);
    if (!line) continue;
    const { str, col, wid } = lineCols(line);
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(str))) {
      if (!m[0]) { re.lastIndex++; continue; }
      const a = m.index, z = a + m[0].length - 1;
      out.push({ y, x: col[a], w: col[z] + wid[z] - col[a] });
      if (out.length > 5000) return out;
    }
  }
  return out;
}

function findRegex(q, isRe) {
  try { return new RegExp(isRe ? q : q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'); } catch { return null; }
}

function openFind(s) {
  const bar = s.pane.querySelector('.findbar'), q = bar.querySelector('.fq');
  if (!bar.wired) wireFind(s, bar);
  bar.hidden = false;
  const sel = s.term.getSelection();
  if (sel && !sel.includes('\n')) q.value = sel;
  q.focus(); q.select();
  if (q.value) runFind(s, 0);
}
function closeFind(s) {
  const bar = s.pane.querySelector('.findbar');
  bar.hidden = true;
  s.find = null;
  s.term.clearSelection();
  s.term.focus();
}
function wireFind(s, bar) {
  bar.wired = true;
  const q = bar.querySelector('.fq');
  q.addEventListener('input', () => runFind(s, 0, true));
  bar.querySelector('.fre input').onchange = () => runFind(s, 0, true);
  q.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); runFind(s, e.shiftKey ? -1 : 1); }
    else if (e.key === 'Escape') { e.preventDefault(); closeFind(s); }
    else if (e.key === 'F3') { e.preventDefault(); runFind(s, e.shiftKey ? -1 : 1); }
  });
  bar.querySelector('.fprev').onclick = () => runFind(s, -1);
  bar.querySelector('.fnext').onclick = () => runFind(s, 1);
  bar.querySelector('.ferr').onclick = () => jumpError(s, 1);
  bar.querySelector('.fx').onclick = () => closeFind(s);
}
// dir: 0 = 처음 찾기(화면 아래쪽에서 가까운 것), 1 다음, -1 이전
function runFind(s, dir, fresh) {
  const bar = s.pane.querySelector('.findbar'), q = bar.querySelector('.fq').value;
  const n = bar.querySelector('.fn');
  if (!q) { n.textContent = ''; s.find = null; s.term.clearSelection(); return; }
  const re = findRegex(q, bar.querySelector('.fre input').checked);
  if (!re) { n.textContent = '정규식 오류'; return; }
  if (fresh || !s.find || s.find.q !== q) {
    const list = findMatches(s, re);
    const b = s.term.buffer.active;
    const bottom = b.viewportY + s.term.rows;
    let i = list.findLastIndex((m) => m.y < bottom);       // 기본: 지금 보이는 곳에서 가장 아래 것
    if (i < 0) i = list.length - 1;
    s.find = { q, list, i };
    if (!dir) dir = 0;
  }
  const f = s.find;
  if (!f.list.length) { n.textContent = '없음'; s.term.clearSelection(); return; }
  f.i = (f.i + dir + f.list.length) % f.list.length;
  selectMatch(s, f.list[f.i]);
  n.textContent = `${f.i + 1} / ${f.list.length}${f.list.length > 5000 ? '+' : ''}`;
}
function selectMatch(s, m) {
  s.term.select(m.x, m.y, m.w);
  const b = s.term.buffer.active;
  if (m.y < b.viewportY || m.y >= b.viewportY + s.term.rows) s.term.scrollToLine(Math.max(0, m.y - (s.term.rows >> 1)));
}
// 빨간색(첫 번째) 하이라이트 규칙에 걸리는 다음/이전 줄로
function jumpError(s, dir) {
  const r = HL_RULES[0];
  if (!r) return toast('키워드 하이라이트 규칙이 없습니다');
  const re = new RegExp(r.re.source, 'gi');
  const list = findMatches(s, re);
  if (!list.length) return toast('에러 표시가 없습니다');
  const cur = s.errAt ?? (s.term.buffer.active.viewportY + s.term.rows - 1);
  const pick = dir > 0 ? (list.find((m) => m.y > cur) || list[0]) : ([...list].reverse().find((m) => m.y < cur) || list[list.length - 1]);
  s.errAt = pick.y;
  selectMatch(s, pick);
  const n = s.pane.querySelector('.findbar .fn');
  if (n) n.textContent = `에러 ${list.findIndex((m) => m === pick) + 1} / ${list.length}`;
}

// 터미널에 포커스가 있을 때의 단축키
function termShortcut(s, e) {
  const cs = e.ctrlKey && e.shiftKey && !e.altKey;
  if (cs && e.code === 'KeyF') { openFind(s); return true; }
  if (cs && e.code === 'KeyS') { saveOutput(s); return true; }
  if (e.key === 'F3' && !e.ctrlKey && !e.altKey) {
    if (s.find) runFind(s, e.shiftKey ? -1 : 1); else openFind(s);
    return true;
  }
  return false;
}

// ── 붙여넣기 확인 (여러 줄·위험 명령) ─────────────────────────
const DANGER_RE = /\b(rm\s+-[a-z]*(r[a-z]*f|f[a-z]*r)|mkfs(\.\w+)?|dd\s+if=|shutdown|reboot|halt|poweroff|init\s+[06]|drop\s+(table|database|schema)|truncate\s+table|systemctl\s+(stop|restart|disable|mask)|kill(all)?\s+-9|chmod\s+-R\s+0?777|chown\s+-R|iptables\s+-F|format\s+[a-z]:|del\s+\/[sq])\b|>\s*\/dev\/sd/i;

async function pasteClipboard(s) {
  let txt;
  try { txt = await navigator.clipboard.readText(); } catch { return toast('클립보드 읽기 권한이 필요합니다'); }
  if (txt) pasteText(s, txt);
}

async function pasteText(s, txt) {
  const body = txt.replace(/\r\n/g, '\n').replace(/\n$/, '');
  const multi = body.includes('\n'), danger = DANGER_RE.test(body);
  const prod = s.spec.color === 'red';
  if (SETTINGS.pasteWarn === false || (!multi && !danger)) return s.term.paste(txt);
  const dlg = $('#pasteDlg'), ta = $('#pasteText');
  ta.value = txt.replace(/\r\n/g, '\n');
  const info = () => {
    const v = ta.value.replace(/\n$/, '');
    $('#pasteInfo').textContent = `${v.split('\n').length}줄 · ${v.length.toLocaleString()}자 → ${tabLabel(s)}`;
    const d = DANGER_RE.exec(v);
    $('#pasteWarn').hidden = !d && !prod;
    $('#pasteWarn').textContent = [prod ? '⚠ 운영(빨강) 세션입니다.' : '', d ? `⚠ 위험할 수 있는 명령: "${d[0]}"` : ''].filter(Boolean).join('  ');
  };
  ta.oninput = info;
  info();
  $('#pasteDelay').value = String(store.get('pasteDelay', 0));
  setTimeout(() => ta.focus());
  if ((await dialogResult(dlg)) !== 'ok') return s.term.focus();
  const delay = +$('#pasteDelay').value;
  store.set('pasteDelay', delay);
  const text = ta.value;
  s.term.focus();
  if (!delay) return s.term.paste(text);
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {               // 장비 CLI 버퍼가 넘치지 않게 줄마다 쉬어 가며 보냄
    const last = i === lines.length - 1;
    if (last && !lines[i]) break;
    s.term.paste(lines[i] + (last ? '' : '\r'));
    if (!last) await sleep(delay);
  }
}

// ── 출력 저장 / 인쇄 ─────────────────────────────────────
function bufferText(s) {
  const b = s.term.buffer.active, out = [];
  for (let y = 0; y < b.length; y++) {
    const l = b.getLine(y);
    if (!l) continue;
    if (l.isWrapped && out.length) out[out.length - 1] += l.translateToString(true);
    else out.push(l.translateToString(true));
  }
  while (out.length && !out[out.length - 1]) out.pop();
  return out.join('\r\n') + '\r\n';
}
function saveOutput(s) {
  const d = new Date(), z = (x) => String(x).padStart(2, '0');
  const name = `${tabLabel(s).replace(/[\\/:*?"<>|]+/g, '_')}_${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}_${z(d.getHours())}${z(d.getMinutes())}.txt`;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['﻿' + bufferText(s)], { type: 'text/plain;charset=utf-8' }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  toast(`저장: ${name}`, 2000);
}
function printOutput(s) {
  const w = window.open('', '_blank', 'width=900,height=700');
  if (!w) return toast('팝업이 막혀 있습니다');
  w.document.title = tabLabel(s);
  const pre = w.document.createElement('pre');
  pre.style.cssText = 'font:11px/1.35 D2Coding,Consolas,monospace;white-space:pre-wrap';
  pre.textContent = bufferText(s);
  w.document.body.appendChild(pre);
  w.focus();
  w.print();
}

// ── 탭: 이름 바꾸기·순서 드래그·색 라벨 ──────────────────────
function renameTab(s) {
  const v = prompt('탭 이름 (비우면 원래 이름)', tabLabel(s));
  if (v == null) return;
  s.customName = v.trim() || null;
  refreshTabLabel(s);
}
function refreshTabLabel(s) {
  s.tab.querySelector('.label').textContent = tabLabel(s);
  renderSessionChrome(s);
  if (focused() === s) document.title = `${tabLabel(s)} — W.S.T`;
}

let dragTab = null;
function setupTabDrag(s) {
  s.tab.draggable = true;
  s.tab.addEventListener('dragstart', (e) => { dragTab = s; e.dataTransfer.effectAllowed = 'move'; s.tab.classList.add('dragging'); });
  s.tab.addEventListener('dragend', () => { dragTab = null; s.tab.classList.remove('dragging'); $$('.tab.drop-l,.tab.drop-r').forEach((t) => t.classList.remove('drop-l', 'drop-r')); });
  s.tab.addEventListener('dragover', (e) => {
    if (!dragTab || dragTab === s) return;
    e.preventDefault();
    const r = s.tab.getBoundingClientRect(), right = e.clientX > r.left + r.width / 2;
    s.tab.classList.toggle('drop-r', right);
    s.tab.classList.toggle('drop-l', !right);
  });
  s.tab.addEventListener('dragleave', () => s.tab.classList.remove('drop-l', 'drop-r'));
  s.tab.addEventListener('drop', (e) => {
    e.preventDefault();
    if (!dragTab || dragTab === s) return;
    const right = s.tab.classList.contains('drop-r');
    s.tab.classList.remove('drop-l', 'drop-r');
    s.tab.parentNode.insertBefore(dragTab.tab, right ? s.tab.nextSibling : s.tab);
    tabs.splice(tabs.indexOf(dragTab), 1);
    tabs.splice(tabs.indexOf(s) + (right ? 1 : 0), 0, dragTab);
  });
}

// 색 라벨: 빨강 = 운영(붙여넣기 경고 + 칸 테두리)
const LABEL_COLORS = {
  red: ['빨강 (운영)', '#e5484d'], orange: ['주황', '#f76b15'], yellow: ['노랑', '#e2a336'],
  green: ['초록', '#30a46c'], blue: ['파랑', '#0b74de'], purple: ['보라', '#8e4ec6'],
};
function applyTabColor(s) {
  const c = LABEL_COLORS[s.spec.color]?.[1];
  for (const el of [s.tab, s.pane]) {
    el.classList.toggle('colored', !!c);
    if (c) el.style.setProperty('--tc', c); else el.style.removeProperty('--tc');
  }
  s.pane.classList.toggle('prod', s.spec.color === 'red');
}

// ── 입력 훅 (MultiExec·매크로 녹화가 붙음) ───────────────────
const inputHooks = [];
function onTermInput(s, d) { for (const h of inputHooks) h(s, d); }

// ── 유휴 방지: 세션 설정 antiIdle초 동안 입력이 없으면 스페이스+지우기 (장비 exec-timeout·방화벽 세션 만료 방지) ──
inputHooks.push((s) => { s.lastInput = Date.now(); });
setInterval(() => {
  const now = Date.now();
  for (const t of tabs) {
    const sec = +t.spec.antiIdle;
    if (!sec || t.state !== 'on' || !isOpen(t)) continue;
    if (now - (t.lastInput || t.connectedAt || now) >= sec * 1000) {
      sendInput(t, new TextEncoder().encode(' \x7f'));
      t.lastInput = now;
    }
  }
}, 5000);

// ── 화면 잠금 (Ctrl+Alt+L): 마스터 비밀번호가 있으면 그것으로, 없으면 잠글 때 정한 PIN으로 풂 ──
async function sha256(txt) {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(txt));
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, '0')).join('');
}
async function lockScreen() {
  let pinHash = null;
  if (!VAULT?.master) {
    const v = await promptSecrets([{ which: 'l', key: 'p1', label: '잠금 해제 PIN (이번 잠금에만 사용)' }, { which: 'l', key: 'p2', label: 'PIN 확인' }], '화면 잠금', true);
    if (!v) return;
    if (!v['l.p1'] || v['l.p1'] !== v['l.p2']) return toast('PIN이 비었거나 서로 다릅니다', 2500);
    pinHash = await sha256(v['l.p1']);
  }
  let dlg = $('#lockDlg');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'lockDlg';
    dlg.className = 'lock';
    dlg.innerHTML = `<form><div class="lock-ic">🔒</div><h3>화면이 잠겼습니다</h3>
      <p class="hint lock-how"></p><input type="password" class="lock-in" autocomplete="off"><p class="error lock-err"></p>
      <button class="primary">잠금 해제</button></form>`;
    document.body.appendChild(dlg);
    dlg.addEventListener('cancel', (e) => e.preventDefault());       // Esc로 닫히지 않게
  }
  dlg.querySelector('.lock-how').textContent = pinHash ? 'PIN을 입력하세요' : '마스터 비밀번호를 입력하세요';
  dlg.querySelector('.lock-err').textContent = '';
  dlg.querySelector('form').onsubmit = async (e) => {
    e.preventDefault();
    const inp = dlg.querySelector('.lock-in'), val = inp.value;
    inp.value = '';
    let ok = false;
    if (pinHash) ok = (await sha256(val)) === pinHash;
    else { try { ok = (await api.call('vaultVerify', { master: val })).ok; } catch {} }
    if (ok) { dlg.close(); focused()?.term.focus(); }
    else dlg.querySelector('.lock-err').textContent = '틀렸습니다';
  };
  document.querySelectorAll('dialog[open]').forEach((d) => d !== dlg && d.close());
  dlg.showModal();
  dlg.querySelector('.lock-in').focus();
}
