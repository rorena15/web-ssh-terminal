'use strict';
/* SSH 터널 — 목록·시작/중지·편집. 실행은 서버가 담당(탭을 닫아도 유지). */

let TUNNEL_STATUS = {};
function setTunnelStatus(st) { TUNNEL_STATUS = st || {}; }
api.on('tunnel', (m) => { TUNNEL_STATUS[m.id] = m.status; renderTunnels(); });

const TSTATE = { on: '실행 중', starting: '연결 중…', reconnecting: '재연결 중…', error: '오류', off: '중지됨' };

// 툴바 ⇄터널·사이드바 탭에 실행 중 개수 / 문제 표시
function renderTunnelBadge() {
  renderAppStatus();
  const sts = (DB.tunnels || []).map((t) => TUNNEL_STATUS[t.id]?.state || 'off');
  const on = sts.filter((x) => x === 'on').length, bad = sts.filter((x) => x === 'error').length;
  const re = sts.filter((x) => x === 'reconnecting' || x === 'starting').length;
  for (const id of ['#tunnelBadge', '#tunnelBadge2']) {
    const b = $(id);
    b.textContent = bad ? `!${bad}` : re ? `↻${re}` : on ? String(on) : '';
    b.className = 'badge' + (bad ? ' bad' : re ? ' warn' : '');
    b.title = `실행 중 ${on} · 재연결 중 ${re} · 오류 ${bad}`;
  }
}

function renderTunnels() {
  renderTunnelBadge();
  const box = $('#tunnelList');
  box.innerHTML = '';
  const list = DB.tunnels || [];
  if (!list.length) {
    box.innerHTML = '<div class="side-empty">터널이 없습니다.<br>＋ 로 추가하세요.<br><small>예: 내 PC 13306 → (점프 서버 경유) → DB 3306</small></div>';
  }
  for (const t of list) {
    const st = TUNNEL_STATUS[t.id] || { state: 'off' };
    const via = findSession(t.via);
    const row = document.createElement('div');
    row.className = 'tn-row ' + st.state;
    row.innerHTML = `<button class="tn-toggle" title="시작/중지"></button>
      <div class="tn-main"><b></b><span class="tn-desc"></span><span class="tn-st"></span></div>`;
    row.querySelector('.tn-toggle').textContent = ['on', 'starting', 'reconnecting'].includes(st.state) ? '■' : '▶';
    row.querySelector('b').textContent = t.name || `터널 ${t.listenPort}`;
    const viaName = via ? sessName(via) : '(세션 없음)';
    row.querySelector('.tn-desc').textContent = (t.type === 'dynamic' ? `SOCKS5 127.0.0.1:${t.listenPort} · via ${viaName}`
      : t.type === 'remote' ? `서버 ${t.remoteBind === '0.0.0.0' ? '*' : '127.0.0.1'}:${t.listenPort} ← ${viaName} → 이 PC ${t.destHost}:${t.destPort}`
      : `127.0.0.1:${t.listenPort} → ${t.destHost}:${t.destPort} · via ${viaName}`) + (t.autoStart ? ' · 자동 시작' : '');
    row.querySelector('.tn-st').textContent = (TSTATE[st.state] || st.state) + (st.conns ? ` · 연결 ${st.conns}` : '') + (st.error ? ` — ${st.error}` : '');
    row.querySelector('.tn-toggle').onclick = () => toggleTunnel(t);
    row.ondblclick = () => editTunnel(t);
    row.oncontextmenu = (e) => {
      e.preventDefault();
      showMenu(e.clientX, e.clientY, [
        { label: ['on', 'starting', 'reconnecting'].includes(st.state) ? '중지' : '시작', action: () => toggleTunnel(t) },
        { label: '편집…', action: () => editTunnel(t) },
        t.type === 'local' ? { label: '주소 복사 (127.0.0.1:' + t.listenPort + ')', action: () => navigator.clipboard.writeText(`127.0.0.1:${t.listenPort}`) } : null,
        '-',
        { label: '삭제', danger: true, action: () => deleteTunnel(t) },
      ]);
    };
    box.appendChild(row);
  }
}

async function toggleTunnel(t) {
  const st = TUNNEL_STATUS[t.id]?.state;
  if (['on', 'starting', 'reconnecting'].includes(st)) {
    await api.call('tunnelStop', { tid: t.id }).catch((e) => toast(e.message, 3000));
    return;
  }
  const via = findSession(t.via);
  if (!via) return toast('경유할 SSH 세션이 없습니다. 터널을 편집하세요.', 3000);
  let ask = {};
  for (;;) {
    const secrets = await ensureSecrets(via, ask);
    if (!secrets) return;
    try {
      await api.call('tunnelStart', { tid: t.id, secrets });
      toast(`터널 시작: ${t.name || t.listenPort}`, 1500);
      return;
    } catch (e) {
      const [kind, which] = (e.code || '').split(':');
      if (kind === 'auth') { forgetSecret(hopOf(via, which) || via, 'password'); ask = { password: which }; toast(e.message, 2500); continue; }
      if (kind === 'passphrase') { forgetSecret(hopOf(via, which) || via, 'passphrase'); ask = { passphrase: which }; if (e.message.includes('틀렸')) toast(e.message, 2500); continue; }
      toast('터널 시작 실패: ' + e.message, 4000);
      return;
    }
  }
}

async function editTunnel(t) {
  const dlg = $('#tunnelDlg'), f = dlg.querySelector('form');
  const sshs = DB.sessions.filter((s) => s.type === 'ssh');
  if (!sshs.length) return toast('먼저 경유할 SSH 세션을 만드세요', 3000);
  $('#tdTitle').textContent = t ? '터널 편집' : '새 터널';
  f.via.replaceChildren(...sshs.map((s) => new Option(`${sessName(s)} — ${targetStr(s)}`, s.id)));
  f.name.value = t?.name || '';
  f.type.value = t?.type || 'local';
  f.listenPort.value = t?.listenPort || '';
  f.via.value = t?.via || (treeSel?.kind === 'session' && findSession(treeSel.id)?.type === 'ssh' ? treeSel.id : sshs[0].id);
  f.destHost.value = t?.destHost || '';
  f.destPort.value = t?.destPort || '';
  f.autoStart.checked = !!t?.autoStart;
  f.remoteAll.checked = t?.remoteBind === '0.0.0.0';
  $('#tdError').textContent = '';
  const sync = () => {
    const ty = f.type.value, dyn = ty === 'dynamic', rem = ty === 'remote';
    f.querySelector('.dest-row').hidden = dyn;
    f.querySelector('.remote-only').hidden = !rem;
    f.querySelector('.lp-label').textContent = rem ? 'SSH 서버 쪽 포트' : '내 PC 포트 (127.0.0.1)';
    f.querySelector('.dh-label').textContent = rem ? '이 PC에서 연결할 대상 호스트' : '원격 대상 호스트';
    f.destHost.placeholder = rem ? '127.0.0.1 (이 PC 기준)' : '127.0.0.1 (SSH 서버 기준)';
    $('#tdHint').textContent = dyn
      ? '브라우저·프로그램의 프록시를 SOCKS5 127.0.0.1:포트로 지정하면 SSH 서버를 거쳐 나갑니다.'
      : rem ? 'SSH 서버의 포트로 들어온 연결이 이 PC를 거쳐 대상(이 PC 기준 주소)으로 전달됩니다. 예: 서버 8080 → 내 PC의 개발 웹서버 3000'
      : '내 PC의 127.0.0.1:포트로 접속하면 SSH 서버를 거쳐 원격 대상에 연결됩니다. 대상 주소는 SSH 서버 기준입니다.';
  };
  f.type.onchange = sync;
  sync();
  for (;;) {
    if ((await dialogResult(dlg)) !== 'save') return;
    const v = {
      id: t?.id || uid(), name: f.name.value.trim(), type: f.type.value, listenPort: +f.listenPort.value, via: f.via.value,
      destHost: f.destHost.value.trim() || '127.0.0.1', destPort: +f.destPort.value, autoStart: f.autoStart.checked,
    };
    if (v.type === 'remote') v.remoteBind = f.remoteAll.checked ? '0.0.0.0' : '127.0.0.1';
    const used = v.type !== 'remote' && (DB.tunnels || []).find((x) => x.type !== 'remote' && x.listenPort === v.listenPort && x.id !== v.id);
    const err = !v.listenPort ? '내 PC 포트를 입력하세요'
      : used ? `포트 ${v.listenPort}는 "${used.name || '다른 터널'}"이 쓰고 있습니다`
      : v.type !== 'dynamic' && !v.destPort ? '대상 포트를 입력하세요' : '';
    if (err) { $('#tdError').textContent = err; continue; }
    if (t) Object.assign(t, v); else (DB.tunnels ||= []).push(v);
    await saveDB();
    renderTunnels();
    if (t && TUNNEL_STATUS[t.id]?.state === 'on') toast('실행 중인 터널은 다시 시작해야 변경 내용이 적용됩니다', 3000);
    return;
  }
}

async function deleteTunnel(t) {
  if (!confirm(`터널 "${t.name || t.listenPort}"을(를) 삭제할까요?`)) return;
  await api.call('tunnelStop', { tid: t.id }).catch(() => {});
  DB.tunnels = DB.tunnels.filter((x) => x !== t);
  delete TUNNEL_STATUS[t.id];
  await saveDB();
  renderTunnels();
}

$('#tunnelAdd').onclick = () => editTunnel(null);
