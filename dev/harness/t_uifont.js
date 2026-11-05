// 화면(인터페이스) 글꼴·글자 크기 시험: 툴바 [터미널|화면] 전환 후 A−/A＋·글꼴 선택이 UI에만 적용되는지 (11/4, Claude 작성)
// 실행: cat lib.js t_uifont.js | PYTHONIOENCODING=utf-8 python cdp.py http://127.0.0.1:18022/ -
const O = { errors: [] };
window.addEventListener('error', (e) => O.errors.push(String(e.message)));
await until(() => typeof openSpec === 'function' && typeof DB !== 'undefined', 8000, 'ready');
const s = await openFake(); await W(300);
const rootPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize);
const menuH = () => { const r = document.createRange(); r.selectNodeContents(document.querySelector('#menubar .mb').firstChild); return r.getBoundingClientRect().height; };
const uiBtn = document.querySelector('#fontCtl [data-font-target=ui]'), termBtn = document.querySelector('#fontCtl [data-font-target=term]');
O.hasToggle = !!uiBtn && !!termBtn;
termBtn.click(); await W(100);
const term0 = s.term.options.fontSize, px0 = rootPx(), h0 = menuH();
uiBtn.click(); await W(150);
O.uiOn = uiBtn.classList.contains('on') && !termBtn.classList.contains('on');
O.valShowsUi = document.querySelector('#fontSizeVal').textContent.trim() === String(Math.round(px0));
document.querySelector('#fontUp').click(); document.querySelector('#fontUp').click(); await W(300);
O.uiGrew = rootPx() === px0 + 2 && menuH() > h0;
O.termSame = s.term.options.fontSize === term0;
const sel = document.querySelector('#fontFamilySel');
const opt = [...sel.options].find((o) => /맑은|Malgun/.test(o.textContent));
if (opt) { sel.value = opt.value; sel.dispatchEvent(new Event('change', { bubbles: true })); await W(200); }
O.uiFamily = /Malgun|맑은/.test(getComputedStyle(document.querySelector('#menubar')).fontFamily);
O.termFamilySame = !/^"?Malgun/.test(s.term.options.fontFamily);
for (let i = 0; i < 10; i++) document.querySelector('#fontUp').click(); await W(300);
O.max18 = rootPx() <= 18;
O.noHScroll = document.documentElement.scrollWidth <= document.documentElement.clientWidth;
document.querySelector('#fontSizeVal').click(); await W(200);
O.resetUi = rootPx() === 12;
termBtn.click(); await W(100);
O.backToTerm = document.querySelector('#fontSizeVal').textContent.trim() === String(s.term.options.fontSize);
O.pass = Object.entries(O).every(([k, v]) => k === 'errors' ? !v.length : v === true);
return O;
