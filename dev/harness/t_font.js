// 글자 크기·글꼴·화면 배율 시험 (11/4, Claude 작성). 실행: cat lib.js t_font.js | PYTHONIOENCODING=utf-8 python cdp.py http://127.0.0.1:18022/ -
const O = { errors: [] };
window.addEventListener('error', (e) => O.errors.push(String(e.message)));
await until(() => typeof openSpec === 'function' && typeof DB !== 'undefined', 8000, 'ready');
const val = () => document.querySelector('#fontSizeVal')?.textContent.trim();
const f0 = fontSize;
// 탭 없이
document.querySelector('#fontUp').click(); await W(200);
O.noTabUp = fontSize === f0 + 1 && val() === String(f0 + 1);
document.querySelector('#fontSizeVal').click(); await W(200);
O.resetShown = val() === String(fontSize);
const base = fontSize;
const s = await openFake(); await W(300);
O.newTabUsesSize = s.term.options.fontSize === base;
document.querySelector('#fontDown').click(); await W(200);
O.downApplied = s.term.options.fontSize === base - 1 && val() === String(base - 1);
s.pane.querySelector('.term').dispatchEvent(new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true, cancelable: true })); await W(200);
O.wheelSync = val() === String(fontSize) && s.term.options.fontSize === fontSize;
const sel = document.querySelector('#fontFamilySel');
const opt = [...sel.options].find((o) => /Consolas/.test(o.textContent));
sel.value = opt.value; sel.dispatchEvent(new Event('change', { bubbles: true })); await W(300);
O.familyApplied = /Consolas/.test(s.term.options.fontFamily) && /Consolas/.test(SETTINGS.fontFamily || '');
// UI 배율 (11/4 화면 글자 크기는 px 지정으로 바뀜 → t_uifont.js가 확인, 여기선 참고값만)
const fsBefore = parseFloat(getComputedStyle(document.querySelector('#menubar')).fontSize) * (parseFloat(getComputedStyle(document.documentElement).zoom) || 1);
const tbBefore = document.querySelector('#menubar').getBoundingClientRect().height;
document.querySelector('#menubar [data-menu=view]').click(); await W(150);
const big = [...document.querySelectorAll('#ctxMenu button')].find((b) => /크게\(110|110%/.test(b.textContent));
big?.click(); await W(300);
O.uiScaleStored = store.get('uiScale');
O.uiScaleChanged = document.querySelector('#menubar').getBoundingClientRect().height > tbBefore;
O.noHScroll = document.documentElement.scrollWidth <= document.documentElement.clientWidth;
O.termUnaffected = s.term.options.fontSize === fontSize;
// 원복
store.set('uiScale', null); if (typeof applyUiScale === 'function') applyUiScale();
setFont(f0);
// 테마 키 이관
O.themeKeys = typeof SCHEMES !== 'undefined' ? Object.keys(SCHEMES).join(',') : (typeof TERM_SCHEMES !== 'undefined' ? Object.keys(TERM_SCHEMES).join(',') : '?');
store.set('termScheme', 'moba');
O.mobaMigrates = typeof schemeKey === 'function' ? schemeKey() : '?';
store.set('termScheme', 'auto');
O.pass = O.noTabUp && O.resetShown && O.newTabUsesSize && O.downApplied && O.wheelSync && O.familyApplied && O.noHScroll && O.termUnaffected && O.mobaMigrates !== 'moba' && O.mobaMigrates !== '?' && !O.errors.length;
return O;
