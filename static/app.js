'use strict';
/* 탭·화면 분할·접속·자동 재접속·모니터링 바·로컬 터미널 */

const DEFAULT_FONT_SIZE = 15;
const FONT_FALLBACK = 'D2Coding, "Cascadia Mono", Consolas, "Malgun Gothic", monospace';
const FONT_FAMILIES = [['D2Coding', 'D2Coding'], ['Cascadia Mono', 'Cascadia Mono'], ['Consolas', 'Consolas'], ['NanumGothicCoding', '나눔고딕코딩'], ['Courier New', 'Courier New']];
const DEFAULT_UI_FONT_SIZE = 12;
const UI_FONT_FAMILIES = [['', '시스템 기본'], ['Malgun Gothic', '맑은 고딕'], ['NanumGothic', '나눔고딕'], ['Dotum', '돋움'], ['Segoe UI', 'Segoe UI']];
let fontTarget = store.get('fontTarget', 'term') === 'ui' ? 'ui' : 'term';
let terminalFontReady = false;
let fontSize = Math.max(9, Math.min(32, +store.get('fontSize', DEFAULT_FONT_SIZE) || DEFAULT_FONT_SIZE));
const tabs = [];                 // 열린 터미널 탭
let layout = store.get('layout', '1');
let cells = [];                  // 분할 칸마다 보여줄 탭
let focusIdx = 0;
const LAYOUT_N = { '1': 1, '2v': 2, '2h': 2, '4': 4 };
const RETRY = [3, 5, 10, 20, 30];


const focused = () => cells[focusIdx] || null;
const tabLabel = (s) => s.customName || s.spec.name || (s.kind === 'localfs' ? '이 PC' : s.kind === 'local' ? shellName(s.spec.shell)
  : s.spec.type === 'serial' ? `${s.spec.com} ${s.spec.baud || 9600}` : targetStr(s.spec));
// 탭 종류: ssh(셸+SFTP) · sftp(파일만) · raw(Telnet/Rlogin/Serial) · local · ftp · vnc
const RAW_TYPES = new Set(['telnet', 'rlogin', 'serial']);
function tabKind(spec) {
  if (spec.type === 'local' || spec.type === 'mosh') return 'local';
  if (RAW_TYPES.has(spec.type)) return 'raw';
  return ['sftp', 'ftp', 'vnc', 'rdpweb', 'localfs'].includes(spec.type) ? spec.type : 'ssh';
}
const shellName = (id) => CAPS.shells.find((x) => x.id === id)?.name || id;

// ── 세션 열기 ────────────────────────────────────────────
function openSpec(spec) {
  if (spec.type && spec.type !== 'ssh' && !featureOn(spec.type) && !spec.quick) toast(`"${spec.type}" 기능은 숨김 상태지만 엽니다 (⚙설정 → 기능 표시)`, 2000);
  if (spec.type === 'rdp' && spec.rdpMode !== 'web') return launchRdp(spec);
  if (spec.type === 'rdp') spec = { ...spec, type: 'rdpweb' };
  if (['local', 'serial', 'mosh', 'localfs'].includes(spec.type) && !CAPS.local) {
    return toast('이 세션은 서버가 127.0.0.1로 실행 중일 때만 쓸 수 있습니다', 3000);
  }
  if (!spec.quick) {
    const recent = store.get('recent', []).filter((x) => x !== spec.id);
    recent.unshift(spec.id);
    store.set('recent', recent.slice(0, 10));
    renderRecent();
  }
  openTab(spec);
}

async function launchRdp(spec) {
  try {
    let secrets = {};
    if (spec.gateway) {
      const gw = findSession(spec.gateway);
      if (!gw) return toast('게이트웨이 SSH 세션을 찾을 수 없습니다', 3000);
      let ask = {};
      for (;;) {
        secrets = await ensureSecrets(gw, ask);
        if (!secrets) return;
        try {
          toast('SSH 게이트웨이 연결 중…');
          const r = await api.call('rdp', { sid: spec.id, secrets });
          return toast(`원격 데스크톱 실행 → ${r.address}`, 2500);
        } catch (e) {
          const [kind, which] = (e.code || '').split(':');
          if (kind === 'auth') { forgetSecret(hopOf(gw, which) || gw, 'password'); ask = { password: which }; toast(e.message, 2500); continue; }
          if (kind === 'passphrase') { forgetSecret(hopOf(gw, which) || gw, 'passphrase'); ask = { passphrase: which }; if (e.message.includes('틀렸')) toast(e.message, 2500); continue; }
          throw e;
        }
      }
    }
    const r = await api.call('rdp', { sid: spec.id, secrets });
    toast(`원격 데스크톱 실행 → ${r.address}`, 2500);
  } catch (e) {
    toast('RDP 실행 실패: ' + e.message, 4000);
  }
}

function openTab(spec) {
  const s = {
    id: uid(), spec, kind: tabKind(spec),
    ws: null, sid: null, state: 'idle', sftp: null, mon: null, retryN: 0, retryTimer: null, ask: {},
  };
  s.tab = document.createElement('div');
  s.tab.className = 'tab';
  s.tab.innerHTML = `<span class="dot"></span><span class="label"></span><button class="x" title="닫기">✕</button>`;
  s.tab.querySelector('.label').textContent = tabLabel(s);
  $('#tabs').appendChild(s.tab);

  s.pane = document.createElement('section');
  s.pane.className = 'pane kind-' + s.kind;
  s.pane.innerHTML = `<div class="pane-title"></div>${FIND_BAR_HTML}<div class="term"></div>
    <div class="banner" hidden><span class="msg"></span><span class="grow"></span>
      <button class="re primary">재접속 (R)</button><button class="cancel" hidden>취소</button><button class="cl">탭 닫기 (Enter)</button></div>`;
  s.pane.querySelector('.pane-title').textContent = tabLabel(s);
  $('#workspace').appendChild(s.pane);
  applyTabColor(s);

  const term = s.term = new Terminal({
    fontFamily: terminalFontFamily(),
    fontSize, theme: termTheme(), cursorBlink: true, cursorInactiveStyle: 'outline', scrollback: +spec.scrollback || +SETTINGS.scrollback || 10000,
    allowProposedApi: true, rightClickSelectsWord: false, overviewRulerWidth: 10,
  });
  s.fit = new FitAddon.FitAddon();
  term.loadAddon(s.fit);
  term.loadAddon(new WebLinksAddon.WebLinksAddon());
  term.open(s.pane.querySelector('.term'));
  s.hl = new Highlighter(term);
  tabs.push(s);

  // 복사·붙여넣기
  term.onSelectionChange(() => {
    const sel = term.getSelection();
    if (sel) navigator.clipboard?.writeText(sel).then(() => toast('복사됨', 800), () => {});
  });
  s.pane.querySelector('.term').addEventListener('contextmenu', (e) => { e.preventDefault(); pasteClipboard(s); });
  s.pane.querySelector('.term').addEventListener('wheel', (e) => {     // Ctrl+휠 = 글자 크기
    if (!e.ctrlKey) return;
    e.preventDefault(); e.stopPropagation();
    setFont(fontSize + (e.deltaY < 0 ? 1 : -1));
  }, { capture: true, passive: false });
  term.attachCustomKeyEventHandler((e) => {
    if (e.type !== 'keydown') return true;
    if (e.ctrlKey && e.shiftKey && e.code === 'KeyC') {
      const sel = term.getSelection();
      if (sel) navigator.clipboard?.writeText(sel).then(() => toast('복사됨', 800));
      return false;
    }
    if ((e.ctrlKey && e.shiftKey && e.code === 'KeyV') || (e.shiftKey && !e.ctrlKey && e.key === 'Insert')) {
      pasteClipboard(s);
      return false;
    }
    if (termShortcut(s, e)) return false;
    if (globalShortcut(e)) return false;
    // 끊긴 탭: R = 재접속, Enter = 탭 닫기
    if (s.state === 'closed' || s.state === 'waiting') {
      if (e.code === 'KeyR' && !e.ctrlKey && !e.altKey) { reconnectNow(s); return false; }
      if (e.key === 'Enter') { closeTab(s, true); return false; }
    }
    return true;
  });

  term.onData((d) => {
    sendInput(s, new TextEncoder().encode(d));
    if (d.includes('\r')) s.cwdPending = true;       // 명령 실행 → 끝나면 SFTP 폴더 따라가기
    onTermInput(s, d);                               // MultiExec·매크로 녹화
  });
  term.onBinary((d) => sendInput(s, Uint8Array.from(d, (c) => c.charCodeAt(0))));
  term.onResize(({ cols, rows }) => sendCtl(s, { type: 'resize', cols, rows }));
  term.onTitleChange((t) => { s.tab.title = t; });

  new ResizeObserver(() => { if (cells.includes(s)) safeFit(s); }).observe(s.pane.querySelector('.term'));
  s.pane.addEventListener('pointerdown', () => { const i = cells.indexOf(s); if (i >= 0 && i !== focusIdx) setFocus(i); }, true);

  s.tab.onclick = () => show(s);
  s.tab.ondblclick = () => renameTab(s);
  setupTabDrag(s);
  s.tab.onauxclick = (e) => { if (e.button === 1) closeTab(s); };
  s.tab.oncontextmenu = (e) => { e.preventDefault(); tabMenu(s, e.clientX, e.clientY); };
  s.tab.querySelector('.x').onclick = (e) => { e.stopPropagation(); closeTab(s); };
  s.pane.querySelector('.re').onclick = () => reconnectNow(s);
  s.pane.querySelector('.cancel').onclick = () => { clearTimeout(s.retryTimer); s.retryTimer = null; setState(s, 'closed', '자동 재접속 취소됨'); };
  s.pane.querySelector('.cl').onclick = () => closeTab(s);

  show(s);
  connect(s);
  return s;
}

const isOpen = (s) => s.ws?.readyState === WebSocket.OPEN && s.state === 'on';
function sendInput(s, bytes) { if (isOpen(s)) s.ws.send(bytes); }
function sendCtl(s, obj) { if (isOpen(s)) s.ws.send(JSON.stringify(obj)); }
function safeFit(s) { try { s.fit.fit(); } catch {} }

function setState(s, state, msg) {
  s.state = state;
  renderTree();
  renderAppStatus();
  const banner = s.pane.querySelector('.banner');
  banner.hidden = !(state === 'closed' || state === 'waiting');
  banner.querySelector('.cancel').hidden = state !== 'waiting';
  if (msg) banner.querySelector('.msg').textContent = msg;
  if (state !== 'on') { s.sid = null; s.mon = null; s.autoSwitched = false; }
  renderSessionChrome(s);
  s.sftp?.sessionChanged();
  if (focused() === s) { showSftpPanel(); renderStatus(); updateToolbar(); }
}

async function connect(s) {
  clearTimeout(s.retryTimer);
  s.retryTimer = null;
  if (s.ws) { s.ws.onclose = null; s.ws.close(); }
  s.closedExit = undefined;
  setState(s, 'connecting');
  const p = s.spec;
  if (s.kind === 'vnc') { s.rfb?.disconnect(); s.rfb = null; return connectVnc(s); }
  let first;
  if (s.kind === 'local') {
    first = p.type === 'mosh' ? { type: 'connect', shell: 'wsl', mosh: { host: p.host, port: p.port || 22, username: p.username, keyPath: p.keyPath || '' } }
      : { type: 'connect', shell: p.shell };
  } else if (s.kind === 'localfs') {
    first = { type: 'connect' };
  } else if (s.kind === 'ftp') {
    const sec = await ensureSecrets(p, s.ask);
    s.ask = {};
    if (!sec) { setState(s, 'closed', '접속 취소됨'); return; }
    first = { type: 'connect', host: p.host, port: p.port || 21, username: p.username, password: sec.password, save: !!sec.save?.target,
              tls: p.ftpTls || '', ftpInsecure: !!p.ftpInsecure, passive: p.passive !== false, encoding: p.encoding || 'utf-8' };
  } else if (s.kind === 'raw') {
    first = { type: 'connect', proto: p.type, host: p.host, port: p.port, username: p.username, encoding: p.encoding || 'utf-8',
              com: p.com, baud: p.baud, bits: p.bits, parity: p.parity, stop: p.stop, flow: p.flow, crlf: !!p.crlf,
              log: { on: !!p.log, name: p.name || p.host || p.com, ts: !!SETTINGS.logTimestamp } };
    if (p.gateway) {                                   // Telnet을 SSH 게이트웨이 경유로
      const gw = findSession(p.gateway);
      if (!gw) { setState(s, 'closed', '게이트웨이 세션 없음'); return; }
      const sec = await ensureSecrets(gw, s.ask);
      s.ask = {};
      if (!sec) { setState(s, 'closed', '접속 취소됨'); return; }
      first.gateway = gwParams(gw, sec);
    }
    s.term.write(`\r\n\x1b[90m${p.type === 'serial' ? `${p.com} ${p.baud || 9600}bps` : `${p.type} ${p.host}:${p.port}`} 연결 중...\x1b[0m\r\n`);
  } else {
    const secrets = await ensureSecrets(p, s.ask);
    s.ask = {};
    if (!secrets) { setState(s, 'closed', '접속 취소됨'); return; }
    const chain = jumpChain(p);
    first = {
      type: 'connect', ...hopParams(p, secrets), encoding: p.encoding || 'utf-8',
      log: { on: !!p.log, name: p.name || p.host, ts: !!SETTINGS.logTimestamp }, monitor: SETTINGS.monitor && focused() === s,
      noShell: s.kind === 'sftp', x11: !!p.x11,
    };
    const via = [first.proxy?.host && `${first.proxy.type || 'socks5'} ${first.proxy.host}`, ...chain.map(targetStr)].filter(Boolean);
    s.term.write(`\r\n\x1b[90m${targetStr(p)}${via.length ? ' (via ' + via.join(' → ') + ')' : ''} 접속 중...\x1b[0m\r\n`);
  }

  const ws = new WebSocket(wsUrl({ local: '/local', raw: '/raw', ftp: '/ftp', localfs: '/localfs' }[s.kind] || '/ws'));
  ws.binaryType = 'arraybuffer';
  s.ws = ws;
  let errorShown = false;

  ws.onopen = () => {
    safeFit(s);
    ws.send(JSON.stringify({ ...first, cols: s.term.cols, rows: s.term.rows }));
  };
  ws.onmessage = async (ev) => {
    if (typeof ev.data !== 'string') {
      s.term.write(new Uint8Array(ev.data));
      if (!cells.includes(s)) s.tab.classList.add('activity');   // 가려진 탭에 새 출력
      if (s.cwdPending) {
        clearTimeout(s.cwdTimer);
        s.cwdTimer = setTimeout(() => { s.cwdPending = false; s.sftp?.followTerminal(); }, 400);
      }
      return;
    }
    const m = JSON.parse(ev.data);
    if (m.type === 'connected') {
      s.sid = m.sid;
      s.retryN = 0;
      s.logPath = m.log;
      s.tab.title = m.log ? `로그: ${m.log}` : '';
      s.connectedAt = Date.now();
      setState(s, 'on');
      syncMonitor();                                 // 접속 중에 포커스가 바뀌었을 수 있음
      if (['ssh', 'sftp', 'ftp', 'localfs'].includes(s.kind)) onSshConnected(s);
      runOnLogin(s);
      if (focused() === s) s.term.focus();
    } else if (m.type === 'hostkey') {
      const ok = await askHostKey(m);
      ws.send(JSON.stringify({ type: 'hostkey_reply', accept: ok }));
    } else if (m.type === 'error') {
      errorShown = true;
      s.term.write(`\r\n\x1b[31m${m.message.replace(/\n/g, '\r\n')}\x1b[0m\r\n`);
      let [kind, which] = (m.code || '').split(':');
      const gw = which?.startsWith('gateway') ? findSession(p.gateway) : null;   // Telnet 등의 SSH 게이트웨이 홉
      if (gw) which = which === 'gateway' ? 'target' : which.replace('gateway', '');
      const hop = hopOf(gw || p, which) || p;
      if (kind === 'auth' && (hop.auth || 'password') === 'password') {
        forgetSecret(hop, 'password');
        s.ask = { password: which };
        setState(s, 'closed', '인증 실패');
        setTimeout(() => connect(s), 50);           // 비밀번호 다시 묻기
      } else if (kind === 'passphrase') {
        forgetSecret(hop, 'passphrase');
        s.ask = { passphrase: which };
        setState(s, 'closed', '키 암호 필요');
        setTimeout(() => connect(s), 50);
      } else if (kind === 'hostkey') {
        setState(s, 'closed', '호스트 키 불일치');
        if (await hostKeyChanged(hop, m.message)) connect(s);
      } else {
        setState(s, 'closed', '접속 실패');
      }
    } else if (m.type === 'closed') {
      s.closedExit = m.exit;
      s.term.write(`\r\n\x1b[90m[연결 종료${m.exit != null ? ` · exit ${m.exit}` : ''}]\x1b[0m\r\n`);
    } else if (m.type === 'monitor') {
      s.mon = m;
      if (focused() === s) renderStatus();
    } else if (m.type === 'notice') {
      toast(m.message, 3000);
    }
  };
  ws.onclose = (ev) => {
    if (s.ws !== ws) return;
    const wasOn = s.state === 'on';
    if (!errorShown && !wasOn) {
      s.term.write(`\r\n\x1b[31m중계 서버에 연결할 수 없습니다 (${ev.code}${ev.reason ? ' ' + ev.reason : ''})\x1b[0m\r\n`);
    }
    if (errorShown) return;
    // 사용자가 exit로 끝낸 경우(종료 코드 있음)는 재접속하지 않음 — 네트워크 끊김만 자동 재접속
    const dropped = wasOn && s.closedExit == null;
    const canRetry = ['ssh', 'sftp', 'ftp'].includes(s.kind) || (s.kind === 'raw' && s.spec.type !== 'serial');
    if (dropped && canRetry && s.spec.reconnect !== false && !api.stopped) scheduleReconnect(s);
    else setState(s, 'closed', s.closedExit != null ? `세션 종료 (exit ${s.closedExit})` : '연결이 끊어졌습니다');
  };
}

// 호스트 키가 바뀜: 사용자가 확인하면 저장된 키만 지우고 다시 접속 → 처음 접속처럼 새 지문 확인 창이 뜸
async function hostKeyChanged(hop, message) {
  const dlg = $('#hkChangedDlg');
  $('#hkcHost').textContent = targetStr(hop);
  $('#hkcDetail').textContent = message.split('\n').filter((l) => /^(저장됨|수신됨)/.test(l)).join('\n');
  if ((await dialogResult(dlg)) !== 'replace') return false;
  try { await api.call('forgetHostKey', { host: hop.host, port: hop.port || 22 }); return true; }
  catch (e) { toast(e.message, 3000); return false; }
}

function scheduleReconnect(s) {
  const wait = RETRY[Math.min(s.retryN, RETRY.length - 1)];
  s.retryN++;
  let left = wait;
  const tick = () => {
    if (left <= 0) { connect(s); return; }
    setState(s, 'waiting', `연결 끊김 — ${left}초 후 자동 재접속 (${s.retryN}번째)`);
    left--;
    s.retryTimer = setTimeout(tick, 1000);
  };
  tick();
}
function reconnectNow(s) { s.retryN = 0; connect(s); }

// 게이트웨이 SSH 세션 → 서버에 넘길 접속 정보 (Telnet·VNC 경유용)
const gwParams = (gw, sec) => hopParams(gw, sec);

function onSshConnected(s) {
  if (['sftp', 'ftp', 'localfs'].includes(s.kind)) {  // SFTP·FTP·이 PC 파일: 파일 탐색기가 탭 화면 전체
    if (!s.sftp) { s.sftp = new SftpPanel(s, s.pane); s.sftp.el.hidden = false; }
    s.sftp.sessionChanged();
    s.sftp.list(s.sftp.cwd);
    return;
  }
  if (!s.sftp) s.sftp = new SftpPanel(s);
  s.sftp.sessionChanged();
  if (focused() === s) {
    showSftpPanel();
    if (!store.get('sidebarCollapsed', false) && $('#vtabs .on')?.dataset.side === 'sessions' && !s.autoSwitched) {
      s.autoSwitched = true;
      setSide('sftp');                               // 접속하면 SFTP 탭으로
    }
  }
  setTimeout(() => s.sftp?.followTerminal(true), 1200);
}

function closeTab(s, force) {
  if (!force && s.state === 'on' && !confirm(`${tabLabel(s)} 연결을 끊을까요?`)) return;
  clearTimeout(s.retryTimer);
  s.sftp?.destroy();
  if (s.rfb) { const r = s.rfb; s.rfb = null; r.disconnect(); }
  if (s.ws) { s.ws.onclose = null; s.ws.close(); }
  s.term.dispose();
  s.tab.remove();
  s.pane.remove();
  const i = tabs.indexOf(s);
  tabs.splice(i, 1);
  const ci = cells.indexOf(s);
  if (ci >= 0) {
    cells[ci] = tabs.find((t) => !cells.includes(t)) || null;   // 빈 칸은 숨겨진 탭으로 채움
  }
  renderLayout();
  renderTree();
}

// ── 화면 분할 ───────────────────────────────────────────
function show(s) {
  const i = cells.indexOf(s);
  if (i >= 0) { setFocus(i); return; }
  // 분할 화면에 빈 칸이 있으면 그 칸부터 채우고, 없으면 포커스된 칸을 바꿈
  const n = LAYOUT_N[layout];
  const empty = cells[focusIdx] ? [...Array(n).keys()].find((k) => !cells[k]) : focusIdx;
  if (empty != null) focusIdx = empty;
  cells[focusIdx] = s;
  renderLayout();
}

function setFocus(i) {
  focusIdx = i;
  renderLayout();
}

// 원격 모니터링은 포커스된 탭 하나만 (가려진 탭이 3초마다 계속 명령을 돌리지 않게)
function syncMonitor() {
  const f = focused();
  tabs.forEach((t) => sendCtl(t, { type: 'monitor', on: !!SETTINGS.monitor && t === f }));
}

function setLayout(mode) {
  layout = mode;
  store.set('layout', mode);
  const n = LAYOUT_N[mode];
  cells = cells.slice(0, n);
  while (cells.length < n) cells.push(tabs.find((t) => !cells.includes(t)) || null);
  if (focusIdx >= n) focusIdx = 0;
  renderLayout();
}

function renderLayout() {
  const n = LAYOUT_N[layout];
  $$('#tbSplit [data-layout]').forEach(b => {
    b.classList.toggle('on', b.dataset.layout === layout);
    b.setAttribute('aria-pressed', b.dataset.layout === layout);
  });
  while (cells.length < n) cells.push(null);
  const wsEl = $('#workspace');
  wsEl.className = 'layout-' + layout;
  $$('.cell-empty', wsEl).forEach((e) => e.remove());
  $('#home').hidden = tabs.length > 0;
  for (const t of tabs) {
    const i = cells.indexOf(t);
    renderSessionChrome(t);
    t.pane.querySelector('.pane-title').classList.toggle('act', i >= 0 && i === focusIdx);
    t.pane.hidden = i < 0;
    t.pane.style.gridArea = i >= 0 ? 'c' + i : '';
    t.pane.classList.toggle('focused', i === focusIdx && n > 1);
    t.tab.classList.toggle('active', i === focusIdx);
    t.tab.classList.toggle('visible', i >= 0);
    if (i >= 0) t.tab.classList.remove('activity');
  }
  if (tabs.length) {
    cells.forEach((c, i) => {
      if (c) return;
      const e = document.createElement('div');
      e.className = 'cell-empty' + (i === focusIdx ? ' focused' : '');
      e.style.gridArea = 'c' + i;
      e.textContent = '탭을 클릭하거나 세션을 더블클릭하면 여기에 열립니다';
      e.onclick = () => setFocus(i);
      wsEl.appendChild(e);
    });
  }
  const f = focused();
  if (f) {
    requestAnimationFrame(() => { cells.forEach((c) => c && safeFit(c)); f.term.focus(); });
    f.tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    document.title = `${tabLabel(f)} — W.S.T`;
  } else {
    document.title = 'W.S.T';
  }
  syncMonitor();
  showSftpPanel();
  renderStatus();
  updateToolbar();
}

// ── 상태 표시줄 (원격 모니터링) ───────────────────────────
function renderStatus() {
  renderAppStatus();
  const el = $('#sbText');
  el.classList.remove('remote');
  const s = focused();
  if (!api.ws || api.ws.readyState !== WebSocket.OPEN) return;
  if (!s) { el.textContent = tabs.length ? '빈 칸' : '준비'; return; }
  if (s.kind === 'local') { el.textContent = s.spec.type === 'mosh' ? `📶 Mosh · ${targetStr(s.spec)}` : `▣ 로컬 · ${shellName(s.spec.shell)}`; return; }
  if (s.kind !== 'ssh') {                            // Telnet·Serial·SFTP·FTP·VNC: 모니터링 없음
    const what = s.spec.type === 'serial' ? `${s.spec.com} ${s.spec.baud || 9600} ${s.spec.bits || 8}${s.spec.parity || 'N'}${s.spec.stop || 1}` : targetStr(s.spec);
    el.textContent = `● ${(TYPE_NAME[s.spec.type] || s.spec.type).toUpperCase()} · ${what} · ${s.state === 'on' ? '연결됨' : s.state === 'connecting' ? '연결 중…' : '끊김'}${s.spec.log ? ' · 로그 기록 중' : ''}`;
    return;
  }
  const who = `● ${targetStr(s.spec)}${s.spec.encoding === 'euc-kr' ? ' · EUC-KR' : ''}${s.spec.log ? ' · 로그 기록 중' : ''}`;
  const m = s.mon;
  if (s.state !== 'on') { el.textContent = `${targetStr(s.spec)} · ${s.state === 'connecting' ? '접속 중…' : '끊김'}`; return; }
  if (!SETTINGS.monitor) { el.textContent = who; return; }
  if (!m) { el.textContent = who + ' · 모니터링 준비 중…'; return; }
  if (m.unsupported) { el.textContent = who + ' · 모니터링: 지원 안 함 (Linux 아님)'; return; }
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
  const text = (v) => escapeHtml(String(v));
  const bar = (value) => {
    const p = Number.isFinite(Number(value)) ? Math.max(0, Math.min(100, Number(value))) : 0;
    return `<span class="meter${p >= 90 ? ' hot' : p >= 70 ? ' warm' : ''}"><i style="width:${p}%"></i></span>`;
  };
  const parts = [`<b>${escapeHtml(who)}</b>`];
  if (m.cpu != null) parts.push(`CPU ${bar(m.cpu)}${Math.round(m.cpu)}%`);
  const mp = pct(m.mem[0], m.mem[1]);
  parts.push(`RAM ${bar(mp)}${text(fmtSize(m.mem[0] * 1024))} / ${text(fmtSize(m.mem[1] * 1024))}`);
  if (m.disk) { const dp = pct(m.disk[0], m.disk[1]); parts.push(`디스크 / ${bar(dp)}${dp}%`); }
  if (m.net) parts.push(`↓ ${text(fmtSize(m.net[0]))}/s ↑ ${text(fmtSize(m.net[1]))}/s`);
  if (m.load != null) parts.push(`Load ${text(m.load.join(' '))}`);
  parts.push(`Up ${text(fmtUptime(m.uptime))}`);
  el.classList.add('remote');
  el.innerHTML = parts.join('<span class="sep">│</span>');
}
function escapeHtml(s) { return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

// ── 탭 메뉴 ───────────────────────────────────────────
function tabMenu(s, x, y) {
  showMenu(x, y, [
    { label: '탭 복제', hint: 'Ctrl+Shift+U', action: () => openTab(s.spec) },
    { label: '재접속', action: () => reconnectNow(s) },
    { label: '탭 이름 바꾸기…', hint: '더블클릭', action: () => renameTab(s) },
    { label: '새 창으로 분리', hint: 'Ctrl+Shift+D', action: () => detachTab(s) },
    s.rfb ? { label: 'Ctrl+Alt+Del 보내기', action: () => vncSendCad(s) } : null,
    s.rfb ? { label: '내 클립보드를 원격으로', action: () => vncPaste(s) } : null,
    { label: '터미널에서 찾기', hint: 'Ctrl+Shift+F', action: () => openFind(s) },
    { label: '출력 내용 저장…', hint: 'Ctrl+Shift+S', action: () => saveOutput(s) },
    { label: '출력 인쇄…', action: () => printOutput(s) },
    s.spec.quick ? { label: '세션으로 저장…', action: () => saveQuickAsSession(s) } : null,
    !s.spec.quick && findSession(s.spec.id) ? { label: '세션 편집…', action: () => editSession(findSession(s.spec.id)) } : null,
    s.logPath ? { label: '로그 폴더 열기', action: () => api.call('openLogs', { name: s.spec.name || s.spec.host }).catch((e) => toast(e.message)) } : null,
    '-',
    { label: '닫기', action: () => closeTab(s) },
    { label: '다른 탭 모두 닫기', action: () => tabs.filter((t) => t !== s).forEach((t) => closeTab(t, true)) },
  ]);
}

// ── 사이드바 ─────────────────────────────────────────
function setSide(name) {
  $$('#vtabs button').forEach((b) => b.classList.toggle('on', b.dataset.side === name));
  $$('.side-pane').forEach((p) => p.classList.toggle('on', p.id === 'side-' + name));
  if (document.body.classList.contains('side-collapsed')) toggleSidebar(false);
  if (name === 'sftp') showSftpPanel(true);   // 사용자가 고른 경우: 비어 있어도 SFTP 탭 유지
}
$$('#vtabs button').forEach((b) => { b.onclick = () => {
  if (b.classList.contains('on') && !document.body.classList.contains('side-collapsed')) toggleSidebar(true);
  else setSide(b.dataset.side);
}; });

function showSftpPanel(manual = false) {
  const f = focused();
  let any = false;
  for (const t of tabs) {
    if (!t.sftp || t.sftp.inPane) continue;
    const on = t === f;
    t.sftp.el.hidden = !on;
    if (on) { any = true; t.sftp.onShow(); }
  }
  $('#sftpEmpty').hidden = any;
  if (!manual && $('#vtabs .on')?.dataset.side === 'sftp' && !(any && f.state === 'on' && f.sid)) setSide('sessions');
}

function toggleSidebar(collapse) {
  const c = collapse ?? !document.body.classList.contains('side-collapsed');
  document.body.classList.toggle('side-collapsed', c);
  store.set('sidebarCollapsed', c);
  requestAnimationFrame(() => cells.forEach((t) => t && safeFit(t)));
}
(() => {
  const side = $('#sidebar');
  side.style.width = store.get('sidebarWidth', 260) / 12 + 'rem';
  if (store.get('sidebarCollapsed', false)) document.body.classList.add('side-collapsed');
  const rz = $('#sideResizer');
  rz.addEventListener('dblclick', () => toggleSidebar());
  rz.addEventListener('pointerdown', (e) => {
    if (document.body.classList.contains('side-collapsed')) return;
    e.preventDefault();
    const x0 = e.clientX, w0 = side.offsetWidth, scale = uiScaleSetting();
    const move = (ev) => { side.style.width = Math.max(200 * scale, Math.min(innerWidth * 0.6, w0 + ev.clientX - x0)) / (12 * scale) + 'rem'; };
    const up = () => {
      removeEventListener('pointermove', move); removeEventListener('pointerup', up);
      store.set('sidebarWidth', side.offsetWidth / scale);
      cells.forEach((t) => t && safeFit(t));
    };
    addEventListener('pointermove', move); addEventListener('pointerup', up);
  });
})();

// ── 툴바 ──────────────────────────────────────────────
function updateToolbar() {
  $('#tbLocal').disabled = !CAPS.local || !CAPS.shells.length;
  $('#homeLocal').disabled = $('#tbLocal').disabled;
}

$$('#tbSplit [data-layout]').forEach(b => { b.onclick = () => setLayout(b.dataset.layout); });

function localMenu(x, y) {
  if (!CAPS.shells.length) return toast('사용할 수 있는 로컬 셸이 없습니다');
  showMenu(x, y, CAPS.shells.map((sh) => ({
    label: sh.name, action: () => openSpec({ id: 'local-' + sh.id, type: 'local', shell: sh.id, name: sh.name, quick: true }),
  })));
}
$('#tbLocal').onclick = (e) => { const r = e.currentTarget.getBoundingClientRect(); localMenu(r.left, r.bottom + 2); };
$('#homeLocal').onclick = (e) => { const r = e.currentTarget.getBoundingClientRect(); localMenu(r.left, r.bottom + 2); };
$('#tbLogs').onclick = () => api.call('openLogs', {}).catch((e) => toast(e.message, 3000));
$('#tbTunnel').onclick = () => setSide('tunnels');

$('#quick').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  const t = parseTarget(e.target.value);
  if (!t) return toast('형식: user@host 또는 user@host:port', 2500);
  e.target.value = '';
  openSpec({ id: 'q-' + uid(), type: 'ssh', quick: true, name: '', ...t, auth: 'password', encoding: 'utf-8',
             log: !!SETTINGS.logDefault, reconnect: true, jump: null });
});

// ── 단축키 / 글자 크기 / 전체화면 ──────────────────────────
function globalShortcut(e) {
  const cs = e.ctrlKey && e.shiftKey && !e.altKey, ca = e.ctrlKey && e.altKey && !e.shiftKey;
  if (e.key === 'F11' && !e.ctrlKey && !e.altKey) { toggleFullscreen(); return true; }
  if (e.key === 'F1' || (cs && e.code === 'KeyP')) { openPalette(); return true; }
  if (e.ctrlKey && !e.altKey && e.code === 'Tab' && tabs.length) {           // 탭 전환: Ctrl+Tab / Ctrl+Shift+Tab
    const i = Math.max(0, tabs.indexOf(focused())), n = tabs.length;
    show(tabs[(i + (e.shiftKey ? -1 : 1) + n) % n]);
    return true;
  }
  if (cs) {
    if (e.code === 'KeyB') { toggleSidebar(); return true; }
    if (e.code === 'KeyQ') { $('#quick').focus(); return true; }
    if (e.code === 'KeyN') { newSession(); return true; }
    if (e.code === 'KeyU' && focused()) { openTab(focused().spec); return true; }
    if (e.code === 'KeyD' && focused()) { detachTab(focused()); return true; }
    if (e.code === 'KeyM') { toggleMultiExec(); return true; }
    return false;
  }
  if (!ca) return false;
  if (e.code === 'KeyN') { newSession(); return true; }
  if ((e.code === 'KeyW' || e.code === 'KeyQ') && focused()) { closeTab(focused()); return true; }
  if (e.code === 'KeyF') { setSide($('#side-sftp').classList.contains('on') ? 'sessions' : 'sftp'); return true; }
  if (e.code === 'KeyL') { lockScreen(); return true; }
  if (e.code === 'KeyT') { const sh = CAPS.shells[0]; if (sh) openSpec({ id: 'local-' + sh.id, type: 'local', shell: sh.id, name: sh.name, quick: true }); return true; }
  const lay = { Digit1: '1', Digit2: '2v', Digit3: '2h', Digit4: '4' }[e.code];
  if (lay) { setLayout(lay); return true; }
  const fk = /^F(\d+)$/.exec(e.key);                                          // Ctrl+Alt+F1~F12 = n번째 탭
  if (fk && tabs[+fk[1] - 1]) { show(tabs[+fk[1] - 1]); return true; }
  if (e.code === 'ArrowRight' || e.code === 'ArrowLeft') {
    if (!tabs.length) return true;
    const i = Math.max(0, tabs.indexOf(focused()));
    const n = tabs.length;
    show(tabs[(i + (e.code === 'ArrowRight' ? 1 : -1) + n) % n]);
    return true;
  }
  return false;
}
document.addEventListener('keydown', (e) => { if (globalShortcut(e)) e.preventDefault(); });

function setFont(n) {
  fontSize = Math.max(9, Math.min(32, n));
  store.set('fontSize', fontSize);
  syncFontControl();
  tabs.forEach((s) => { s.term.options.fontSize = fontSize; });
  cells.forEach((t) => t && safeFit(t));
  toast(`터미널 글자 크기 ${fontSize}px`);
}
$('#fontUp').onclick = () => fontTarget === 'ui' ? setUiFontSize(uiFontSizeSetting() + 1) : setFont(fontSize + 1);
$('#fontDown').onclick = () => fontTarget === 'ui' ? setUiFontSize(uiFontSizeSetting() - 1) : setFont(fontSize - 1);
$('#fontSizeVal').onclick = () => fontTarget === 'ui' ? setUiFontSize(DEFAULT_UI_FONT_SIZE) : setFont(DEFAULT_FONT_SIZE);
$$('[data-font-target]').forEach(b => { b.onclick = () => {
  fontTarget = b.dataset.fontTarget;
  store.set('fontTarget', fontTarget);
  syncFontControl();
}; });

function syncFontControl() {
  const ui = fontTarget === 'ui', label = ui ? '화면' : '터미널';
  const size = ui ? uiFontSizeSetting() : fontSize, base = ui ? DEFAULT_UI_FONT_SIZE : DEFAULT_FONT_SIZE;
  const sel = $('#fontFamilySel');
  sel.replaceChildren(...(ui ? uiFontFamilyItems() : fontFamilyItems()).map(([value, name]) => new Option(name, value)));
  sel.value = ui ? uiFontFamilySetting() : SETTINGS.fontFamily || 'D2Coding';
  sel.disabled = !ui && !terminalFontReady;
  sel.title = label + ' 글꼴';
  sel.setAttribute('aria-label', sel.title);
  $('#fontCtl').setAttribute('aria-label', label + ' 글꼴과 크기');
  $$('[data-font-target]').forEach(b => {
    const on = b.dataset.fontTarget === fontTarget;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', String(on));
  });
  const val = $('#fontSizeVal');
  val.textContent = size;
  val.title = `${label} 글자 크기 ${size}px, 기본 크기(${base}px)로 되돌리기`;
  val.setAttribute('aria-label', val.title);
  for (const [id, text] of [['#fontDown', '작게'], ['#fontUp', '크게']]) {
    $(id).title = `${label} 글자 ${text}`;
    $(id).setAttribute('aria-label', $(id).title);
  }
}

function terminalFontFamily() {
  return SETTINGS.fontFamily ? SETTINGS.fontFamily + ', ' + FONT_FALLBACK : FONT_FALLBACK;
}
function fontFamilyItems() {
  const value = SETTINGS.fontFamily || 'D2Coding';
  return FONT_FAMILIES.some(([key]) => key === value) ? FONT_FAMILIES : [...FONT_FAMILIES, [value, '사용자 지정: ' + value]];
}
function syncFontFamily() {
  syncFontControl();
  $('#settingsDlg [name=fontFamily]').value = SETTINGS.fontFamily || '';
  tabs.forEach((s) => { s.term.options.fontFamily = terminalFontFamily(); safeFit(s); });
  // 설치된 글꼴의 로딩이 끝난 뒤에도 셀 너비를 다시 계산한다.
  document.fonts?.ready.then(() => cells.forEach((s) => s && safeFit(s)));
}
let fontSaveQueue = Promise.resolve();
let savedFontFamily = null;
function setFontFamily(value) {
  if (!terminalFontReady) return fontSaveQueue;
  if (savedFontFamily === null) savedFontFamily = SETTINGS.fontFamily || '';
  SETTINGS = { ...SETTINGS, fontFamily: value };
  syncFontFamily();
  fontSaveQueue = fontSaveQueue.then(async () => {
    try {
      const r = await api.call('saveSettings', { settings: { ...SETTINGS, fontFamily: value } });
      LOGDIR = r.logDir;
      savedFontFamily = value;
    } catch (e) {
      if (SETTINGS.fontFamily === value) { SETTINGS = { ...SETTINGS, fontFamily: savedFontFamily }; syncFontFamily(); }
      toast('글꼴 저장 실패: ' + e.message, 3000);
    }
  });
  return fontSaveQueue;
}
$('#fontFamilySel').onchange = (e) => fontTarget === 'ui' ? setUiFontFamily(e.target.value) : setFontFamily(e.target.value);
syncFontFamily();

function uiFontSizeSetting() {
  const value = +store.get('uiFontSize', DEFAULT_UI_FONT_SIZE);
  return Number.isFinite(value) ? Math.max(11, Math.min(18, Math.round(value))) : DEFAULT_UI_FONT_SIZE;
}
function uiFontFamilySetting() {
  const value = store.get('uiFontFamily', '');
  return typeof value === 'string' ? value : '';
}
function uiFontFamilyItems() {
  const value = uiFontFamilySetting();
  return UI_FONT_FAMILIES.some(([key]) => key === value) ? UI_FONT_FAMILIES : [...UI_FONT_FAMILIES, [value, '사용자 지정: ' + value]];
}
function syncUiFontSettings() {
  const sel = $('#settingsDlg [name=uiFontFamily]');
  sel.replaceChildren(...uiFontFamilyItems().map(([value, label]) => new Option(label, value)));
  sel.value = uiFontFamilySetting();
  $('#settingsDlg [name=uiFontSize]').value = uiFontSizeSetting();
  syncFontControl();
}
function setUiFontSize(value) {
  const n = Number(value);
  const size = Number.isFinite(n) ? Math.max(11, Math.min(18, Math.round(n))) : DEFAULT_UI_FONT_SIZE;
  store.set('uiFontSize', size);
  document.documentElement.style.fontSize = size + 'px';
  syncUiFontSettings();
  requestAnimationFrame(() => cells.forEach((s) => s && safeFit(s)));
}
function setUiFontFamily(value) {
  store.set('uiFontFamily', value);
  if (value) document.documentElement.style.setProperty('--ui-font-family', value + ', var(--ui-font-fallback)');
  else document.documentElement.style.removeProperty('--ui-font-family');
  syncUiFontSettings();
  requestAnimationFrame(() => cells.forEach((s) => s && safeFit(s)));
  document.fonts?.ready.then(() => cells.forEach((s) => s && safeFit(s)));
}
function uiScaleSetting() { return uiFontSizeSetting() / DEFAULT_UI_FONT_SIZE; }
function setUiScale(value) {
  setUiFontSize(DEFAULT_UI_FONT_SIZE * +value);
}
if (store.get('uiFontSize', null) === null) {
  const scale = +store.get('uiScale', 1);
  setUiScale([0.9, 1, 1.1, 1.25].includes(scale) ? scale : 1);
}
try { localStorage.removeItem('webssh.uiScale'); } catch {}
setUiFontSize(uiFontSizeSetting());
setUiFontFamily(uiFontFamilySetting());

async function toggleFullscreen() {
  if (document.fullscreenElement) return document.exitFullscreen();
  await document.documentElement.requestFullscreen();
  try { await navigator.keyboard?.lock(); } catch {}
  toast('전체화면 — 나가려면 Esc를 길게 누르세요', 2500);
}
$('#fullBtn').onclick = toggleFullscreen;
document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement) navigator.keyboard?.unlock();
  $('#fullBtn').classList.toggle('on', !!document.fullscreenElement);
});

window.addEventListener('beforeunload', (e) => {
  if (tabs.some((s) => s.state === 'on')) e.preventDefault();
});

function renderSessionChrome(s) {
  const label = s.tab.querySelector('.label');
  label.textContent = tabLabel(s);
  s.tab.querySelector('.dot').className = 'dot ' + stateClass(s.state);
  let pt = s.tab.querySelector('.pt');
  if (!pt) { pt = document.createElement('span'); pt.className = 'pt'; label.before(pt); }
  pt.textContent = protocolLabel(s.spec);
  s.tab.querySelector('.prod')?.remove();
  if (s.spec.color === 'red') { const p = document.createElement('span'); p.className = 'prod'; p.textContent = '운영'; label.after(p); }
  const head = s.pane.querySelector('.pane-title');
  head.innerHTML = sessionMarkup(s.spec, tabLabel(s), s.state) + '<span class="grow"></span>' +
    (s.pane.classList.contains('me-target') ? '<span class="chip me">동시입력</span>' : '') +
    (s.state === 'on' && s.logPath ? '<span class="chip">로그</span>' : '');
  if (s.sftp) s.sftp.el.querySelector('.sf-who').innerHTML = sessionMarkup(s.spec, tabLabel(s), s.state);
}
function renderAppStatus() {
  const el = $('#sbApp');
  const statuses = typeof TUNNEL_STATUS === 'undefined' ? {} : TUNNEL_STATUS;
  const running = (DB.tunnels || []).filter(t => statuses[t.id]?.state === 'on').length;
  const clock = new Date().toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit', hour12:false});
  el.textContent = (running ? '터널 ' + running + ' · ' : '') + '탭 ' + tabs.length + ' · 연결 ' + tabs.filter(t => t.state === 'on').length + ' · ' + clock;
}
setInterval(renderAppStatus, 60000);
$('#quickGo').onclick = () => $('#quick').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
$('#meBadge').onclick = () => $('#multiBar .me-line')?.focus();

function menubarItems(name) {
  const click = id => () => $(id).click();
  const item = (label, action, hint, feature, disabled = false) => ({label, action, hint, feature, disabled});
  const tab = (label, action, hint) => ({label, hint, disabled: !focused(), action: () => { const s = focused(); if (s) action(s); }});
  const split = [['1','한 화면'],['2v','좌우 분할'],['2h','상하 분할'],['4','4분할']].map(([m,l],i) => item((layout === m ? '✓ ' : '') + l, () => setLayout(m), 'Ctrl+Alt+' + (i+1), 'split'));
  return {
    file: [item('새 세션', click('#tbSession'), 'Ctrl+Alt+N'), item('로컬 터미널', click('#tbLocal'), 'Ctrl+Alt+T', 'local', $('#tbLocal').disabled), '-', item('세션 가져오기', click('#treeImport')), item('세션 내보내기', click('#treeExport')), '-', item('설정', click('#tbSettings')), item('서버 종료', click('#shutdownBtn'))],
    view: [item('사이드바 접기/펴기', () => toggleSidebar(), 'Ctrl+Shift+B'), ...split, '-', item('라이트/다크 전환', click('#themeBtn')), item('터미널 글자 크게', () => setFont(fontSize + 1)), item('터미널 글자 작게', () => setFont(fontSize - 1)), item('터미널 글자 기본', () => setFont(DEFAULT_FONT_SIZE)), '-',
      ...fontFamilyItems().map(([value, label]) => item(((SETTINGS.fontFamily || 'D2Coding') === value ? '✓ ' : '') + '터미널 글꼴: ' + label, () => setFontFamily(value), '', undefined, !terminalFontReady)), '-',
      item('화면 글자 크게', () => setUiFontSize(uiFontSizeSetting() + 1)), item('화면 글자 작게', () => setUiFontSize(uiFontSizeSetting() - 1)), item('화면 글자 기본', () => setUiFontSize(DEFAULT_UI_FONT_SIZE)), '-',
      ...uiFontFamilyItems().map(([value, label]) => item((uiFontFamilySetting() === value ? '✓ ' : '') + '화면 글꼴: ' + label, () => setUiFontFamily(value))), '-',
      item('전체화면', click('#fullBtn'), 'F11'), item('명령 팔레트', click('#tbPalette'), 'Ctrl+Shift+P / F1')],
    term: [tab('터미널에서 찾기', openFind, 'Ctrl+Shift+F'), tab('출력 저장', saveOutput, 'Ctrl+Shift+S'), tab('탭 복제', s => openTab(s.spec), 'Ctrl+Shift+U'), tab('탭 닫기', closeTab, 'Ctrl+Alt+W'), '-', item('MultiExec 켜기/끄기', click('#tbMulti'), 'Ctrl+Shift+M', 'multiexec'), item('매크로', click('#tbMacro'), '', 'macro')],
    tools: [item('터널', click('#tbTunnel'), '', 'tunnels'), item('도구', click('#tbTools'), '', 'tools'), item('세션 로그 폴더', click('#tbLogs'), '', 'logs')],
    help: [item('단축키 안내', () => openHelp()), item('버전 정보', () => openAbout()), item('라이선스', () => openLicense())]
  }[name];
}
function openMenubar(b) {
  const r = b.getBoundingClientRect();
  showMenu(r.left, r.bottom, menubarItems(b.dataset.menu));
  $('#ctxMenu').dataset.menu = b.dataset.menu;
}
$$('#menubar .mb').forEach(b => {
  b.onclick = () => {
    const m = $('#ctxMenu');
    if (!m.hidden && m.dataset.menu === b.dataset.menu) hideMenu();
    else openMenubar(b);
  };
  b.onmouseenter = () => { if (!$('#ctxMenu').hidden && $('#ctxMenu').dataset.menu) openMenubar(b); };
});
