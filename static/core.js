'use strict';
/* 공통: 유틸, 서버 API(/api), 비밀번호 캐시, 호스트 키 확인, 컨텍스트 메뉴 */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));

const TOKEN = (() => {
  const url = new URL(location.href);
  let token = url.searchParams.get('t');
  try {
    if (token !== null) sessionStorage.setItem('webssh.token', token);
    else token = sessionStorage.getItem('webssh.token');
  } catch {}
  if (url.searchParams.has('t')) {
    url.searchParams.delete('t');
    history.replaceState(history.state, '', url.pathname + url.search + url.hash);
  }
  return token;
})();
const WS_BASE = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
function wsUrl(path, q = {}) {
  const p = new URLSearchParams(q);
  if (TOKEN) p.set('t', TOKEN);
  const qs = p.toString();
  return WS_BASE + path + (qs ? '?' + qs : '');
}

const store = {   // 브라우저별 편의 설정 (글자 크기, 펼친 폴더 등)
  get(k, d) { try { return JSON.parse(localStorage.getItem('webssh.' + k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem('webssh.' + k, JSON.stringify(v)); } catch {} },
};

function toast(msg, ms = 1600) {
  const t = $('#toast');
  t.textContent = msg;
  try { t.hidePopover(); t.showPopover(); } catch {}   // 대화상자가 열려 있어도 그 위에 보이게 (top layer)
  t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), ms);
}

function fmtSize(n) {
  if (n == null) return '';
  if (n < 1024) return n + ' B';
  const u = ['KB', 'MB', 'GB', 'TB'];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return n.toFixed(n < 10 ? 1 : 0) + ' ' + u[i];
}
function fmtTime(t) {
  if (!t) return '';
  const d = new Date(t * 1000), z = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}`;
}
function fmtUptime(s) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}일 ${h}시간` : h ? `${h}시간 ${m}분` : `${m}분`;
}

// 대상 문자열: user@host[:port]
function parseTarget(s) {
  const m = (s || '').trim().match(/^([^@\s]+)@(\[[^\]]+\]|[^:\s]+)(?::(\d+))?$/);
  if (!m) return null;
  return { username: m[1], host: m[2].replace(/^\[|\]$/g, ''), port: m[3] ? +m[3] : 22 };
}
const targetStr = (p) => `${p.username ? p.username + '@' : ''}${p.host}${p.port && +p.port !== 22 ? ':' + p.port : ''}`;

// ── 서버 API ─────────────────────────────────────────────
let DB = { folders: [], sessions: [], tunnels: [] };   // data/sessions.json
let SETTINGS = {};
let CAPS = { local: false, shells: [], rdp: false };
let capsReady;
const CAPS_READY = new Promise((r) => { capsReady = r; });
let LOGDIR = '';

const api = {
  ws: null, n: 0, pending: new Map(), handlers: {}, readyResolve: null,
  ready: null,
  connect() {
    this.ready = new Promise((r) => { this.readyResolve = r; });
    const ws = this.ws = new WebSocket(wsUrl('/api'));
    ws.onopen = () => {
      this.readyResolve();
      if (this.opened) this.onReopen?.();      // 서버 재시작 후 다시 붙으면 데이터 새로 읽기
      this.opened = true;
    };
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id != null && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id);
        this.pending.delete(m.id);
        if (m.error) { const e = new Error(m.error); e.code = m.code; rej(e); } else res(m);
        return;
      }
      if (m.type === 'hostkey') {
        askHostKey(m).then((ok) => ws.send(JSON.stringify({ op: 'hostkey_reply', qid: m.qid, accept: ok })));
        return;
      }
      (this.handlers[m.type] || []).forEach((f) => f(m));
    };
    ws.onclose = () => {
      for (const { rej } of this.pending.values()) rej(new Error('서버 연결이 끊어졌습니다'));
      this.pending.clear();
      if (this.stopped) {
        $('#sbText').textContent = '서버를 종료했습니다. 이 창을 닫으세요. (다시 쓰려면 W.S.T.exe 실행)';
        return;
      }
      $('#sbText').textContent = '⚠ 중계 서버와 연결이 끊어졌습니다 — W.S.T.exe를 다시 실행하세요 (자동 재연결 시도 중)';
      setTimeout(() => this.connect(), 3000);
    };
  },
  async call(op, args = {}) {
    await this.ready;
    const id = ++this.n;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, op, ...args }));
    });
  },
  on(type, f) { (this.handlers[type] ||= []).push(f); },
};

function saveDB() {
  return api.call('saveData', { data: DB }).catch((e) => toast('저장 실패: ' + e.message, 3000));
}
// 공유 세션 파일(설정의 sharedPath)에서 읽은 세션 — 읽기 전용, sessions.json에는 저장 안 함
let SHARED = [];
const allSessions = () => (SHARED.length ? [...DB.sessions, ...SHARED] : DB.sessions);
const findSession = (id) => DB.sessions.find((s) => s.id === id) || SHARED.find((s) => s.id === id);

// ── 비밀번호 / 키 암호 ─────────────────────────────────────
// SECRETS: 이 창이 열린 동안만 기억(메모리). VAULT: 서버의 저장소(DPAPI) 상태 — 비밀번호 자체는 브라우저로 오지 않음.
const SECRETS = new Map();
const credKey = (c) => `${c.username}@${c.host}:${c.port || 22}`;
let VAULT = null;            // {locked, master, keys: [...]} | null(외부 바인딩 등으로 못 씀)
const vaultHas = (c) => !!VAULT && !VAULT.locked && VAULT.keys.includes(credKey(c));
api.on('vault', (m) => { VAULT = m.vault; });

// 마스터 비밀번호로 잠긴 저장소 열기. 취소하면 false (그냥 비밀번호를 물어봄)
async function unlockVault() {
  if (!VAULT?.locked) return true;
  for (;;) {
    const v = await promptSecrets([{ which: 'vault', key: 'master', label: '마스터 비밀번호 (저장된 비밀번호를 쓰려면)' }], '비밀번호 저장소 잠금 해제', true);
    if (!v) return false;
    try { VAULT = (await api.call('vaultUnlock', { master: v['vault.master'] })).vault; return true; }
    catch (e) { toast(e.message, 2500); }
  }
}

/** spec(SSH 세션)에 필요한 비밀값을 모아 반환. 취소하면 null.
 *  ask: {password: 'target'|'jump', passphrase: 'target'|'jump'} — 실패 후 다시 묻기
 *  여러 탭이 동시에 불러도 하나씩 처리: 입력창이 섞이지 않고, 같은 서버는 앞에서 기억한 값을 다시 씀 */
let secretQueue = Promise.resolve();
function ensureSecrets(spec, ask = {}) {
  const p = secretQueue.then(() => ensureSecretsNow(spec, ask));
  secretQueue = p.catch(() => {});
  return p;
}
// 점프 호스트 사슬: 저장된 SSH 세션을 점프로 쓰면(jumpVia) 그 세션의 점프까지 따라감 → [첫 홉, …] (대상 제외)
function jumpChain(spec, depth = 0) {
  if (spec.jumpVia) {
    const j = findSession(spec.jumpVia);
    if (!j || j.id === spec.id || depth > 4) return [];
    return [...jumpChain(j, depth + 1), j];
  }
  return spec.jump?.host ? [spec.jump] : [];
}
const hopNames = (n) => (n === 1 ? ['jump'] : [...Array(n).keys()].map((i) => 'jump' + i));
// 서버에 보낼 홉 정보 (비밀값 포함). sec = ensureSecrets 결과
function hopParams(spec, sec, extra = {}) {
  const chain = jumpChain(spec), names = hopNames(chain.length);
  const hop = (c, v, save) => ({ host: c.host, port: c.port || 22, username: c.username, auth: c.auth || 'password',
                                 keyPath: c.keyPath || '', password: v?.password, passphrase: v?.passphrase, save: !!save,
                                 agent: !!c.agent, keepalive: +c.keepalive || 0, compress: !!c.compress });
  const hops = chain.map((c, i) => hop(c, sec.hops?.[names[i]], sec.save?.[names[i]]));
  const proxy = (spec.proxy?.host ? spec.proxy : chain[0]?.proxy?.host ? chain[0].proxy : null);
  return { ...hop(spec, sec, sec.save?.target), ...extra, jump: hops.length === 1 ? hops[0] : null,
           jumps: hops.length > 1 ? hops : null, proxy };
}
const hopOf = (spec, which) => {             // 오류 코드의 which(target/jump/jumpN) → 해당 홉 설정
  if (!which || which === 'target') return spec;
  const chain = jumpChain(spec);
  return which === 'jump' ? chain[0] : chain[+which.slice(4)];
};

async function ensureSecretsNow(spec, ask) {
  const chain = jumpChain(spec);
  const hops = [...chain.map((c, i) => [hopNames(chain.length)[i], c]), ['target', spec]];
  const needPw = (c, which) => (c.auth || 'password') === 'password' && !(SECRETS.get(credKey(c)) || {}).password && ask.password !== which;
  if (VAULT?.locked && hops.some(([w, c]) => needPw(c, w))) await unlockVault();
  const fields = [];
  for (const [which, c] of hops) {
    const cache = SECRETS.get(credKey(c)) || {};
    const label = which.startsWith('jump') ? `점프 호스트 ${targetStr(c)}` : targetStr(c);
    // 저장소에 있으면 묻지 않음(서버가 채움). 저장된 값으로 실패했으면(ask) 다시 물음
    if ((c.auth || 'password') === 'password' && (cache.password == null || ask.password === which) && (ask.password === which || !vaultHas(c))) {
      fields.push({ which, key: 'password', label: `${label} 비밀번호` });
    }
    if (ask.passphrase === which) fields.push({ which, key: 'passphrase', label: `${label} 개인키 암호` });
  }
  const save = {};
  if (fields.length) {
    const vals = await promptSecrets(fields, spec.name || targetStr(spec), false, hops.some(([, c]) => vaultHas(c)));
    if (!vals) return null;
    for (const [which, c] of hops) {
      const k = credKey(c);
      const cache = { ...(SECRETS.get(k) || {}) };
      for (const f of fields.filter((f) => f.which === which)) cache[f.key] = vals[`${which}.${f.key}`];
      if (vals.remember) SECRETS.set(k, cache); else c._oneShot = cache;
      if (vals.save && fields.some((f) => f.which === which)) save[which] = true;
    }
  }
  const get = (c) => { const v = c._oneShot || SECRETS.get(credKey(c)) || {}; delete c._oneShot; return v; };
  const t = get(spec), hv = {};
  for (const [which, c] of hops) if (which !== 'target') hv[which] = get(c);
  const j = hv.jump || {};
  if (Object.keys(save).length) setTimeout(refreshVault, 4000);              // 접속에 성공하면 서버가 저장 → 목록 갱신
  return { password: t.password, passphrase: t.passphrase, jumpPassword: j.password, jumpPassphrase: j.passphrase, hops: hv, save };
}
function refreshVault() { api.call('vaultStatus').then((r) => { VAULT = r.vault; }, () => {}); }

function forgetSecret(c, key) {
  const k = credKey(c), v = SECRETS.get(k);
  if (v) { delete v[key]; }
}

function promptSecrets(fields, title, noSave, saveDefault) {
  const dlg = $('#secretDlg');
  $('#secTitle').textContent = title;
  // "이 PC에 저장"은 저장소를 쓸 수 있고 기능이 켜져 있을 때만 (마스터 입력창에는 안 보임)
  const canSave = !noSave && VAULT && !VAULT.locked && featureOn('passwordSave');
  $('#secSaveRow').hidden = !canSave;
  $('#secRemember').closest('label').hidden = !!noSave;
  $('#secSave').checked = canSave && (saveDefault || !!store.get('vaultSaveDefault', false));
  const box = $('#secFields');
  box.innerHTML = '';
  for (const f of fields) {
    const l = document.createElement('label');
    l.textContent = f.label;
    const i = document.createElement('input');
    i.type = 'password';
    i.name = `${f.which}.${f.key}`;
    l.appendChild(i);
    box.appendChild(l);
  }
  dlg.returnValue = '';
  dlg.showModal();
  box.querySelector('input')?.focus();
  return new Promise((res) => {
    dlg.addEventListener('close', () => {
      if (dlg.returnValue !== 'ok') return res(null);
      const vals = { remember: noSave || $('#secRemember').checked, save: !$('#secSaveRow').hidden && $('#secSave').checked };
      if (!$('#secSaveRow').hidden) store.set('vaultSaveDefault', vals.save);
      $$('input', box).forEach((i) => { vals[i.name] = i.value; i.value = ''; });
      res(vals);
    }, { once: true });
  });
}

// ── 호스트 키 확인 (여러 요청이 와도 하나씩) ─────────────────
const hostkeyQueue = [];
function askHostKey(m) {
  return new Promise((res) => {
    hostkeyQueue.push({ m, res });
    if (hostkeyQueue.length === 1) showNextHostKey();
  });
}
function showNextHostKey() {
  const item = hostkeyQueue[0];
  if (!item) return;
  const dlg = $('#hostkeyDlg');
  $('#hkHost').textContent = item.m.host;
  $('#hkFp').textContent = `${item.m.keytype}  ${item.m.fingerprint}`;
  dlg.returnValue = '';
  dlg.showModal();
  dlg.addEventListener('close', () => {
    hostkeyQueue.shift();
    item.res(dlg.returnValue === 'yes');
    showNextHostKey();
  }, { once: true });
}

// ── 컨텍스트 메뉴 ────────────────────────────────────────
function showMenu(x, y, items) {
  const m = $('#ctxMenu');
  delete m.dataset.menu;
  m.innerHTML = '';
  for (const it of items) {
    if (!it) continue;
    if (it === '-') { m.appendChild(document.createElement('hr')); continue; }
    const b = document.createElement('button');
    if (it.feature) {
      b.dataset.feature = it.feature;
      b.classList.toggle('feat-off', !featureOn(it.feature));
    }
    b.textContent = it.label;
    if (it.hint) { const h = document.createElement('span'); h.className = 'hint'; h.textContent = it.hint; b.appendChild(h); }
    if (it.danger) b.classList.add('danger');
    b.disabled = !!it.disabled;
    b.onclick = () => { hideMenu(); it.action(); };
    m.appendChild(b);
  }
  m.hidden = false;
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, innerWidth - r.width - 4) + 'px';
  m.style.top = Math.min(y, innerHeight - r.height - 4) + 'px';
}
function hideMenu() { const m = $('#ctxMenu'); m.hidden = true; delete m.dataset.menu; }
addEventListener('pointerdown', (e) => { if (!e.target.closest('#ctxMenu, #menubar .mb')) hideMenu(); });
addEventListener('keydown', (e) => { if (e.key === 'Escape') hideMenu(); });
addEventListener('blur', hideMenu);

// 폼에서 Enter를 누르면 브라우저는 '첫 번째' 제출 버튼을 누른다 → 취소가 앞에 있으면 Enter = 취소가 됨.
// 기본(파란) 버튼이 아닌 버튼은 제출 버튼에서 빼서, Enter는 항상 기본 버튼으로 가게 한다.
$$('dialog form[method=dialog] button[value]:not(.primary)').forEach((b) => {
  b.type = 'button';
  b.addEventListener('click', () => b.closest('dialog').close(b.value));
});

// 대화상자 열고 닫힐 때까지 대기 → returnValue
function dialogResult(dlg) {
  dlg.returnValue = '';
  dlg.showModal();
  return new Promise((res) => dlg.addEventListener('close', () => res(dlg.returnValue), { once: true }));
}

// 공통 단색 SVG와 세션 표기. 사용자 문자열은 escapeHtml/textContent로만 넣는다.
const UI_ICONS = {"menu":"M4 6h16M4 12h16M4 18h16","session":"M3 4h18v16H3zM7 8l3 4-3 4M13 16h4","local":"M3 4h18v16H3zM6 8l3 3-3 3M12 15h6","multi":"M3 7h15M3 12h15M3 17h15M17 4l4 3-4 3","macro":"M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14M12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4","tunnel":"M3 8h17l-4-4M21 16H4l4 4","tools":"M14 3l7 7-4 4-7-7zM12 12L4 20","logs":"M6 3h9l3 3v15H6zM9 10h6M9 14h6","settings":"M12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M5 19l3-3M16 8l3-3M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6","folder":"M3 6h7l2 3h9v11H3z","file":"M6 3h9l3 3v15H6zM14 3v5h4","plus":"M12 4v16M4 12h16","import":"M12 3v12M7 10l5 5 5-5M4 16v5h16v-5","export":"M12 16V4M7 9l5-5 5 5M4 16v5h16v-5","theme":"M12 3a9 9 0 1 0 9 9 9 9 0 0 1-9-9","down":"M3 20L8 5l5 15M5 14h6M16 6h6","up":"M3 20L8 5l5 15M5 14h6M16 6h6M19 3v6","full":"M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5","link":"M10 14l4-4M8 16l-2 2a4 4 0 0 1-6-6l4-4M16 8l2-2a4 4 0 0 1 6 6l-4 4"};
function uiIcon(name) {
  return '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + (UI_ICONS[name] || UI_ICONS.session) + '"></path></svg>';
}
const PROTOCOL_LABELS = {ssh:'SSH',sftp:'SFTP',rdp:'RDP',rdpweb:'RDP',telnet:'TEL',serial:'SER',ftp:'FTP',vnc:'VNC',mosh:'MOSH',rlogin:'RLG',local:'LOC',localfs:'LOC'};
function protocolLabel(spec) { return PROTOCOL_LABELS[spec.type || 'ssh'] || 'SSH'; }
function stateClass(state) { return state === 'on' ? 'on' : ['closed','waiting'].includes(state) ? 'bad' : state ? 'connecting' : 'off'; }
function sessionState(spec) {
  const opened = tabs.filter(t => t.spec.id === spec.id);
  return opened.some(t => t.state === 'on') ? 'on' : opened.some(t => !['closed','waiting'].includes(t.state)) ? 'connecting' : opened.length ? 'closed' : null;
}
function sessionMarkup(spec, name, state) {
  return '<span class="dot ' + stateClass(state) + '"></span><span class="pt">' + protocolLabel(spec) + '</span><span class="label">' + escapeHtml(name || '') + '</span>' + (spec.color === 'red' ? '<span class="prod">운영</span>' : '');
}
