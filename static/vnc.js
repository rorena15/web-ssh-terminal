'use strict';
/* VNC 탭 (noVNC, static/vendor/novnc — MPL-2.0). 서버(/api vncOpen)가 대상에 먼저 연결하고 표를 주면 /vnc?vt=로 이어받는다.
 * VNC 비밀번호는 RFB 프로토콜상 브라우저(noVNC)가 처리하므로 저장소에 넣지 않고 그때그때 묻는다. */

let RFBClass = null;
async function loadRFB() {
  if (!RFBClass) RFBClass = (await import('./vendor/novnc/core/rfb.js')).default;
  return RFBClass;
}

async function connectVnc(s) {
  const p = s.spec;
  if (!p.id || p.quick || !findSession(p.id)) { setState(s, 'closed', 'VNC는 저장된 세션으로만 열 수 있습니다'); return; }
  let secrets = {};
  if (p.gateway) {
    const gw = findSession(p.gateway);
    if (!gw) { setState(s, 'closed', '게이트웨이 세션 없음'); return; }
    secrets = await ensureSecrets(gw, s.ask);
    s.ask = {};
    if (!secrets) { setState(s, 'closed', '접속 취소됨'); return; }
  }
  let box = s.pane.querySelector('.vnc');
  if (!box) {
    box = document.createElement('div');
    box.className = 'vnc';
    s.pane.insertBefore(box, s.pane.querySelector('.banner'));
  }
  box.innerHTML = `<div class="vnc-msg">${escapeHtml(targetStr(p))} 연결 중…</div>`;
  let ticket;
  try {
    ticket = (await api.call('vncOpen', { sid: p.id, secrets })).ticket;
  } catch (e) {
    const [kind, which] = (e.code || '').split(':');
    if (kind === 'auth' && p.gateway) {
      const gw = findSession(p.gateway);
      forgetSecret(hopOf(gw, which) || gw, 'password');
      s.ask = { password: which };
      setState(s, 'closed', '게이트웨이 인증 실패');
      setTimeout(() => connectVnc(s), 50);
      return;
    }
    if (kind === 'passphrase' && p.gateway) {
      const gw = findSession(p.gateway);
      forgetSecret(hopOf(gw, which) || gw, 'passphrase');
      s.ask = { passphrase: which };
      if (e.message.includes('틀렸')) toast(e.message, 2500);
      setState(s, 'closed', '게이트웨이 키 암호 필요');
      setTimeout(() => connectVnc(s), 50);
      return;
    }
    box.querySelector('.vnc-msg').textContent = e.message;
    setState(s, 'closed', '접속 실패');
    return;
  }
  const RFB = await loadRFB();
  box.innerHTML = '';
  const rfb = s.rfb = new RFB(box, wsUrl('/vnc', { vt: ticket }), { shared: true });
  rfb.scaleViewport = p.vncScale !== 'real';
  rfb.resizeSession = false;
  rfb.viewOnly = !!p.viewOnly;
  rfb.focusOnClick = true;
  rfb.addEventListener('connect', () => {
    s.retryN = 0;
    setState(s, 'on');
    if (focused() === s) rfb.focus();
  });
  rfb.addEventListener('disconnect', (e) => {
    if (s.rfb !== rfb) return;
    s.rfb = null;
    const clean = e.detail?.clean;
    setState(s, 'closed', clean ? 'VNC 연결 종료' : 'VNC 연결이 끊어졌습니다');
  });
  rfb.addEventListener('credentialsrequired', async (e) => {
    const types = e.detail?.types || ['password'];
    const fields = types.filter((t) => t === 'username' || t === 'password').map((t) => ({ which: 'vnc', key: t, label: t === 'username' ? '사용자' : 'VNC 비밀번호' }));
    const v = await promptSecrets(fields, `VNC — ${sessName(p)}`, true);
    if (!v) return rfb.disconnect();
    rfb.sendCredentials({ username: v['vnc.username'], password: v['vnc.password'] });
  });
  rfb.addEventListener('securityfailure', (e) => toast(`VNC 인증 실패: ${e.detail?.reason || ''}`, 3500));
  rfb.addEventListener('clipboard', (e) => navigator.clipboard?.writeText(e.detail.text).catch(() => {}));
  rfb.addEventListener('desktopname', (e) => { s.tab.title = e.detail.name; });
}

// 탭 메뉴·팔레트에서 쓰는 VNC 동작
function vncSendCad(s) { s.rfb?.sendCtrlAltDel(); }
async function vncPaste(s) {
  try { const t = await navigator.clipboard.readText(); if (t) { s.rfb?.clipboardPasteFrom(t); toast('원격 클립보드로 보냄 — 원격에서 Ctrl+V', 2000); } }
  catch { toast('클립보드 읽기 권한이 필요합니다'); }
}
paletteAction({ label: 'VNC: Ctrl+Alt+Del 보내기', feature: 'vnc', tab: true, run: (s) => (s?.rfb ? vncSendCad(s) : toast('VNC 탭이 아닙니다')) });
paletteAction({ label: 'VNC: 내 클립보드를 원격으로', feature: 'vnc', tab: true, run: (s) => (s?.rfb ? vncPaste(s) : toast('VNC 탭이 아닙니다')) });
