'use strict';
/* 🧰 도구 메뉴: 포트 스캐너 · 이 PC의 열린 포트 · TFTP/HTTP 서버 · SSH 키 생성 · 알려진 호스트 · 원격 상세 정보.
 * 이 PC에서 동작하는 기능이라 서버가 127.0.0.1로 실행 중일 때만 쓸 수 있다. */

// 공용 도구 창: body(html) 넣고 열기. 닫힐 때까지 기다리지 않음.
function toolWindow(title, html, wide) {
  let dlg = $('#toolDlg');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'toolDlg';
    dlg.className = 'dlg tool';
    dlg.innerHTML = '<div class="tool-head"><h3></h3><button class="tool-x" title="닫기">✕</button></div><div class="tool-body"></div>';
    document.body.appendChild(dlg);
    dlg.querySelector('.tool-x').onclick = () => dlg.close();
  }
  if (dlg.open) dlg.close();
  dlg.classList.toggle('wide', !!wide);
  dlg.querySelector('h3').textContent = title;
  const body = dlg.querySelector('.tool-body');
  body.innerHTML = html;
  dlg.showModal();
  return body;
}
const needLocal = () => { if (CAPS.local) return false; toast('도구는 서버가 127.0.0.1로 실행 중일 때만 쓸 수 있습니다', 3000); return true; };

function toolsMenu(x, y) {
  showMenu(x, y, [
    { label: '포트 스캐너…', action: portScanner },
    { label: '이 PC의 열린 포트…', action: listeningPorts },
    '-',
    { label: 'TFTP 서버…', hint: '장비 설정·펌웨어', action: () => serverTool('tftp') },
    { label: 'HTTP 파일 서버…', hint: '폴더 공유', action: () => serverTool('http') },
    '-',
    { label: 'SSH 키 생성…', action: keygenTool },
    { label: '알려진 호스트 관리…', action: knownHostsTool },
    focused()?.kind === 'ssh' && focused().state === 'on' ? { label: '원격 서버 상세 (프로세스·디스크·포트)…', action: () => remoteDetail(focused()) } : null,
  ]);
}
$('#tbTools').onclick = (e) => { const r = e.currentTarget.getBoundingClientRect(); toolsMenu(r.left, r.bottom + 2); };

// ── 포트 스캐너 ────────────────────────────────────────────
const SCAN_DEFAULT = '21,22,23,25,53,80,110,135,139,143,161,389,443,445,1433,1521,3306,3389,5432,5900,5985,6379,8080,8443,9200,27017';
function portScanner(host) {
  if (needLocal()) return;
  const b = toolWindow('포트 스캐너', `
    <p class="hint">허가받은 대상에만 사용하세요. TCP 연결 시도(connect) 방식이며 결과는 이 PC에서 본 기준입니다.</p>
    <div class="grid3">
      <label class="span2">대상 <span class="hint">(IP · 호스트명 · 10.0.0.1-20 · 10.0.0.0/24)</span><input class="sc-h mono" spellcheck="false"></label>
      <label>시간 제한(초)<input class="sc-t" type="number" step="0.1" min="0.2" max="5" value="0.8"></label>
    </div>
    <label>포트 <span class="hint">(쉼표·범위, 예: 22,80,8000-8100)</span><input class="sc-p mono" spellcheck="false"></label>
    <div class="row"><button class="primary sc-go">검사</button><progress class="sc-pr" max="1" value="0" hidden></progress><span class="sc-st hint grow"></span></div>
    <div class="tool-table sc-res"></div>`, true);
  const h = $('.sc-h', b), p = $('.sc-p', b);
  h.value = host || store.get('scanHost', focused()?.spec?.host || '');
  p.value = store.get('scanPorts', SCAN_DEFAULT);
  h.focus();
  const go = async () => {
    store.set('scanHost', h.value); store.set('scanPorts', p.value);
    const btn = $('.sc-go', b), pr = $('.sc-pr', b), st = $('.sc-st', b);
    btn.disabled = true; pr.hidden = false; pr.value = 0; st.textContent = '검사 중…';
    const off = (m) => { pr.value = m.done / m.total; st.textContent = `${m.done.toLocaleString()} / ${m.total.toLocaleString()}`; };
    api.on('scanProgress', off);
    const t0 = Date.now();
    try {
      const r = await api.call('portScan', { hosts: h.value, ports: p.value, timeout: +$('.sc-t', b).value });
      st.textContent = `열린 포트 ${r.open.length}개 · 호스트 ${r.hosts} × 포트 ${r.ports} · ${((Date.now() - t0) / 1000).toFixed(1)}초`;
      $('.sc-res', b).innerHTML = r.open.length ? `<table><tr><th>호스트</th><th>포트</th><th>서비스</th><th>배너</th><th></th></tr>${
        r.open.map((o) => `<tr><td class="mono">${escapeHtml(o.host)}</td><td>${o.port}</td><td>${escapeHtml(o.service)}</td><td class="mono dim">${escapeHtml(o.banner)}</td>
          <td>${[22, 23, 21, 5900].includes(o.port) ? `<button data-h="${escapeHtml(o.host)}" data-p="${o.port}">열기</button>` : ''}</td></tr>`).join('')}</table>` : '<p class="hint">열린 포트 없음</p>';
      $$('.sc-res button', b).forEach((x) => {
        x.onclick = () => {
          const port = +x.dataset.p, type = { 22: 'ssh', 23: 'telnet', 21: 'ftp', 5900: 'vnc' }[port];
          $('#toolDlg').close();
          editSession(null, '', { type, host: x.dataset.h, port });
        };
      });
    } catch (e) { st.textContent = e.message; }
    finally {
      btn.disabled = false; pr.hidden = true;
      api.handlers.scanProgress = (api.handlers.scanProgress || []).filter((f) => f !== off);
    }
  };
  $('.sc-go', b).onclick = go;
  [h, p].forEach((i) => i.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); }));
}

// ── 이 PC의 열린 포트 ───────────────────────────────────────
async function listeningPorts() {
  if (needLocal()) return;
  const b = toolWindow('이 PC의 열린 포트 (LISTEN)', '<input class="lp-f" placeholder="필터 (포트·프로세스)" spellcheck="false"><div class="tool-table lp-res">불러오는 중…</div>', true);
  let list = [];
  try { list = (await api.call('listening')).ports; } catch (e) { $('.lp-res', b).textContent = e.message; return; }
  const render = () => {
    const q = $('.lp-f', b).value.trim().toLowerCase();
    const rows = list.filter((x) => !q || String(x.port).includes(q) || x.proc.toLowerCase().includes(q));
    $('.lp-res', b).innerHTML = `<table><tr><th>포트</th><th>주소</th><th>PID</th><th>프로세스</th></tr>${rows.map((x) =>
      `<tr><td>${x.port}</td><td class="mono${/^(0\.0\.0\.0|\[::\])$/.test(x.addr) ? ' warn-t' : ''}">${escapeHtml(x.addr)}</td><td>${x.pid}</td><td>${escapeHtml(x.proc)}</td></tr>`).join('')}</table>
      <p class="hint">주황 주소(0.0.0.0 / ::)는 다른 PC에서도 접속할 수 있는 포트입니다.</p>`;
  };
  $('.lp-f', b).oninput = render;
  render();
}

// ── TFTP / HTTP 서버 ───────────────────────────────────────
async function serverTool(kind) {
  if (needLocal()) return;
  const name = kind === 'tftp' ? 'TFTP 서버' : 'HTTP 파일 서버';
  const b = toolWindow(name, `
    <p class="hint">${kind === 'tftp' ? '스위치·방화벽 등 장비의 설정 백업/펌웨어 전송용. UDP 69번.' : '폴더를 웹으로 공유 (읽기 전용, 목록 보기). 다른 PC에서 http://내IP:포트/ 로 받기.'}
      0.0.0.0으로 열면 같은 네트워크의 다른 장비가 접속할 수 있습니다 — 다 쓰면 끄세요.</p>
    <label>폴더<span class="row"><input class="sv-root mono" spellcheck="false"><button class="sv-pick">찾기…</button></span></label>
    <div class="grid3">
      <label>주소<select class="sv-bind"></select></label>
      <label>포트<input class="sv-port" type="number" min="1" max="65535"></label>
      <label class="check sv-w"${kind === 'tftp' ? '' : ' hidden'}><input type="checkbox" class="sv-write"> 업로드(쓰기) 허용</label>
    </div>
    <div class="row"><button class="primary sv-go"></button><span class="sv-st grow hint"></span></div>
    <pre class="sv-log mono"></pre>`);
  const st = await api.call('servers');
  $('.sv-bind', b).innerHTML = ['0.0.0.0', '127.0.0.1', ...st.ips].map((ip) => `<option>${ip}</option>`).join('');
  const prev = store.get('srv.' + kind, {});
  $('.sv-root', b).value = prev.root || '';
  $('.sv-bind', b).value = prev.bind || '0.0.0.0';
  $('.sv-port', b).value = prev.port || (kind === 'tftp' ? 69 : 8000);
  $('.sv-write', b).checked = !!prev.write;
  const paint = (servers, ips) => {
    const s = servers[kind];
    $('.sv-go', b).textContent = s ? '■ 중지' : '▶ 시작';
    $('.sv-go', b).classList.toggle('danger-fill', !!s);
    $$('.sv-root,.sv-bind,.sv-port,.sv-write,.sv-pick', b).forEach((x) => { x.disabled = !!s; });
    const hosts = s ? (s.bind === '0.0.0.0' ? ips : [s.bind]) : [];
    $('.sv-st', b).textContent = s ? `실행 중 — ${hosts.map((ip) => kind === 'http' ? `http://${ip}:${s.port}/` : `${ip}:${s.port}`).join('  ')}` : '중지됨';
    $('.sv-log', b).textContent = (s?.log || []).join('\n');
    $('#tbTools').classList.toggle('on', Object.keys(servers).length > 0);
  };
  paint(st.servers, st.ips);
  $('.sv-pick', b).onclick = async () => { const r = await api.call('pickFolder').catch(() => ({})); if (r.path) $('.sv-root', b).value = r.path; };
  $('.sv-go', b).onclick = async () => {
    try {
      const cur = (await api.call('servers')).servers[kind];
      const r = cur ? await api.call('serverStop', { kind })
        : await api.call('serverStart', { kind, root: $('.sv-root', b).value.trim(), bind: $('.sv-bind', b).value, port: +$('.sv-port', b).value, write: $('.sv-write', b).checked });
      if (!cur) store.set('srv.' + kind, { root: $('.sv-root', b).value.trim(), bind: $('.sv-bind', b).value, port: +$('.sv-port', b).value, write: $('.sv-write', b).checked });
      paint(r.servers, r.ips);
    } catch (e) { toast(e.message, 3500); }
  };
  const timer = setInterval(async () => {
    if (!$('#toolDlg').open) return clearInterval(timer);
    try { const r = await api.call('servers'); paint(r.servers, r.ips); } catch {}
  }, 2000);
}

// ── SSH 키 생성 ────────────────────────────────────────────
function keygenTool() {
  if (needLocal()) return;
  const d = new Date(), z = (x) => String(x).padStart(2, '0');
  const b = toolWindow('SSH 키 생성', `
    <div class="grid3">
      <label>종류<select class="kg-t"><option value="ed25519">Ed25519 (권장)</option><option value="rsa">RSA</option><option value="ecdsa">ECDSA P-256</option></select></label>
      <label>RSA 크기<select class="kg-b"><option>4096</option><option>3072</option><option>2048</option></select></label>
      <label>설명(주석)<input class="kg-c" spellcheck="false"></label>
    </div>
    <div class="grid2">
      <label>키 암호 <span class="hint">(선택)</span><input class="kg-p" type="password"></label>
      <label>키 암호 확인<input class="kg-p2" type="password"></label>
    </div>
    <label>저장 위치 <span class="hint">(비우면 저장하지 않고 화면에만 표시)</span><input class="kg-s mono" spellcheck="false"></label>
    <div class="row"><button class="primary kg-go">생성</button><span class="kg-st grow hint"></span></div>
    <label>공개키 <span class="hint">(서버의 ~/.ssh/authorized_keys에 넣을 것)</span><textarea class="kg-pub mono" rows="3" readonly></textarea></label>
    <div class="row kg-act" hidden><button class="kg-copy">공개키 복사</button><button class="kg-inst">열린 SSH 탭의 서버에 등록…</button></div>
    <textarea class="kg-priv mono" rows="6" readonly hidden></textarea>`, true);
  $('.kg-c', b).value = `webssh@${location.hostname}-${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}`;
  const syncPath = () => { $('.kg-s', b).value = `%USERPROFILE%\\.ssh\\id_${$('.kg-t', b).value}_${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}`; };
  syncPath();
  $('.kg-t', b).onchange = () => { syncPath(); $('.kg-b', b).disabled = $('.kg-t', b).value !== 'rsa'; };
  $('.kg-b', b).disabled = true;
  $('.kg-go', b).onclick = async () => {
    if ($('.kg-p', b).value !== $('.kg-p2', b).value) return toast('키 암호가 서로 다릅니다');
    $('.kg-st', b).textContent = '생성 중…';
    try {
      const r = await api.call('keygen', { kind: $('.kg-t', b).value, bits: +$('.kg-b', b).value, comment: $('.kg-c', b).value,
                                           passphrase: $('.kg-p', b).value, saveAs: $('.kg-s', b).value.trim() });
      $('.kg-pub', b).value = r.public;
      $('.kg-st', b).textContent = r.saved ? `저장됨: ${r.saved} (+ .pub)` : '저장하지 않음 — 아래 개인키를 안전한 곳에 보관하세요';
      $('.kg-priv', b).hidden = !r.private;
      $('.kg-priv', b).value = r.private || '';
      $('.kg-act', b).hidden = false;
      b.dataset.saved = r.saved || '';
    } catch (e) { $('.kg-st', b).textContent = e.message; }
  };
  $('.kg-copy', b).onclick = () => navigator.clipboard.writeText($('.kg-pub', b).value).then(() => toast('복사됨'));
  $('.kg-inst', b).onclick = (e) => {
    const live = tabs.filter((t) => t.kind === 'ssh' && t.state === 'on');
    if (!live.length) return toast('연결된 SSH 탭이 없습니다');
    const r = e.currentTarget.getBoundingClientRect();
    showMenu(r.left, r.bottom + 2, live.map((t) => ({
      label: `${tabLabel(t)} (${targetStr(t.spec)})`,
      action: async () => {
        try {
          await api.call('installPubKey', { sid: t.sid, pub: $('.kg-pub', b).value });
          toast(`${targetStr(t.spec)}에 등록됨`, 2500);
          const saved = b.dataset.saved;
          const sess = findSession(t.spec.id);
          if (saved && sess && confirm(`세션 "${sessName(sess)}"을(를) 이 키로 로그인하도록 바꿀까요?`)) {
            Object.assign(sess, { auth: 'keyfile', keyPath: saved });
            await saveDB(); renderTree();
          }
        } catch (err) { toast(err.message, 3500); }
      },
    })));
  };
}

// ── 알려진 호스트 ──────────────────────────────────────────
async function knownHostsTool() {
  const b = toolWindow('알려진 호스트 (호스트 키)', '<input class="kh-f" placeholder="필터" spellcheck="false"><div class="tool-table kh-res">불러오는 중…</div>', true);
  const load = async () => {
    const list = (await api.call('knownHosts')).hosts;
    const q = $('.kh-f', b).value.trim().toLowerCase();
    $('.kh-res', b).innerHTML = `<table><tr><th>호스트</th><th>종류</th><th>지문</th><th></th></tr>${list.filter((h) => !q || h.name.toLowerCase().includes(q)).map((h) =>
      `<tr><td class="mono">${escapeHtml(h.name)}</td><td>${escapeHtml(h.type)}</td><td class="mono dim">${escapeHtml(h.fingerprint)}</td><td><button data-n="${escapeHtml(h.name)}">지우기</button></td></tr>`).join('')}</table>`;
    $$('.kh-res button', b).forEach((x) => {
      x.onclick = async () => {
        if (!confirm(`${x.dataset.n}의 저장된 호스트 키를 지울까요? (다음 접속 때 다시 확인)`)) return;
        await api.call('forgetHostKey', { name: x.dataset.n });
        load();
      };
    });
  };
  $('.kh-f', b).oninput = load;
  load().catch((e) => { $('.kh-res', b).textContent = e.message; });
}

// ── 원격 서버 상세 (모니터링 바 클릭) ─────────────────────────
async function remoteDetail(s) {
  if (!s || s.kind !== 'ssh' || s.state !== 'on') return;
  const b = toolWindow(`${tabLabel(s)} — 상세`, '<div class="rd">불러오는 중…</div>', true);
  try {
    const r = await api.call('remoteDetail', { sid: s.sid });
    $('.rd', b).innerHTML = Object.entries(r.sections).map(([k, v]) => `<h4>${escapeHtml(k)}</h4><pre class="mono rd-pre">${escapeHtml(v)}</pre>`).join('');
  } catch (e) { $('.rd', b).textContent = e.message; }
}
$('#statusbar').addEventListener('click', () => { const f = focused(); if (f?.mon && !f.mon.unsupported) remoteDetail(f); });

paletteAction({ label: '포트 스캐너', feature: 'tools', run: () => portScanner() });
paletteAction({ label: '이 PC의 열린 포트', feature: 'tools', run: () => listeningPorts() });
paletteAction({ label: 'TFTP 서버', feature: 'tools', run: () => serverTool('tftp') });
paletteAction({ label: 'HTTP 파일 서버', feature: 'tools', run: () => serverTool('http') });
paletteAction({ label: 'SSH 키 생성', feature: 'tools', run: () => keygenTool() });
paletteAction({ label: '알려진 호스트 관리', run: () => knownHostsTool() });
paletteAction({ label: '원격 서버 상세 (프로세스·디스크·포트)', tab: true, run: (s) => remoteDetail(s) });
