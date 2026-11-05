// lib.js와 함께 실행. 가짜 SSH 서버: 2222(기본), 2223(--deny-file-access).
const denied = await openFake(2223);
setSide('sftp');
await until(() => denied.sftp?.el.classList.contains('unavailable'), 8000, 'unavailable');
const panel = denied.sftp, el = panel.el;
const check = (ok, message) => { if (!ok) throw new Error(message); };
check(el.querySelector('.sf-detail').textContent.includes('255'), 'missing exit code');
check(el.querySelector('.sf-reason').textContent.includes('셸 명령'), 'missing fallback reason');
const measurements = [];
const side = document.querySelector('#sidebar');
const oldStyle = side.getAttribute('style');
const oldFont = document.documentElement.style.fontSize;
const oldTheme = document.documentElement.dataset.theme;
try {
  for (const theme of ['light', 'dark']) {
    document.documentElement.dataset.theme = theme;
    for (let px = 11; px <= 18; px++) {
      document.documentElement.style.fontSize = px + 'px';
      for (let width = 200; width <= 400; width += 25) {
        side.style.cssText += `;width:${width}px;min-width:${width}px;max-width:${width}px`;
        await W(20);
        const state = el.querySelector('.sf-unavailable');
        check(getComputedStyle(el.querySelector('.sf-bar')).display === 'none', 'toolbar visible');
        check(getComputedStyle(el.querySelector('.sf-cols')).display === 'none', 'columns visible');
        check(getComputedStyle(el.querySelector('.sf-content')).display === 'none', 'list visible');
        check(state.scrollWidth <= state.clientWidth + 1, `overflow ${theme}/${px}/${width}`);
        const button = el.querySelector('[data-a="retry"]');
        button.scrollIntoView({ block: 'nearest' });
        const a = state.getBoundingClientRect(), b = button.getBoundingClientRect();
        check(b.top >= a.top && b.bottom <= a.bottom + 1, 'retry clipped');
        measurements.push({ theme, px, width });
      }
    }
  }
  el.querySelector('[data-a="retry"]').click();
  await until(() => !el.querySelector('[data-a="retry"]').disabled, 8000, 'retry');
  check(el.classList.contains('unavailable'), 'failed retry lost empty state');
} finally {
  if (oldStyle === null) side.removeAttribute('style'); else side.setAttribute('style', oldStyle);
  document.documentElement.style.fontSize = oldFont;
  if (oldTheme === undefined) delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = oldTheme;
}
const normal = await openFake(2222);
setSide('sftp');
await until(() => normal.sftp?.cwd, 8000, 'normal list');
const good = normal.sftp;
await good.list('/does-not-exist');
check(!good.el.classList.contains('unavailable'), 'folder error hid toolbar');
check(!good.el.querySelector('.sf-msg').hidden, 'missing operation error');
const message = good.el.querySelector('.sf-msg').getBoundingClientRect();
const columns = good.el.querySelector('.sf-cols').getBoundingClientRect();
check(message.top >= columns.bottom, 'message overlaps toolbar');
await good.list('/');
check(good.el.querySelector('.sf-msg').hidden, 'success kept error');
return { pass: true, layouts: measurements.length, retry: true, operationError: true, recovery: true };
