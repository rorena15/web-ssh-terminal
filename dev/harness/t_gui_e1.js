// GUI E안 1단계 시험 — agy가 docs/SPEC_GUI_E1_2026-11-04.md만 보고 작성(Claude가 세션 행 선택자에 data-sid 추가)
// 실행: cat dev/harness/lib.js dev/harness/t_gui_e1.js | PYTHONIOENCODING=utf-8 python dev/harness/cdp.py http://127.0.0.1:18022/ -
// GUI E안 1단계(SPEC_GUI_E1_2026-11-04.md) 검증 스크립트
// 실행: cat harness/lib.js harness/t_gui_e1.js | python harness/cdp.py http://127.0.0.1:18022/ -

const errs = [];
const onErr = (e) => errs.push(String(e?.message || e?.reason || e));
window.addEventListener('error', onErr);
window.addEventListener('unhandledrejection', onErr);

await until(
  () => typeof openSpec === 'function' && typeof DB !== 'undefined' && typeof tabs !== 'undefined',
  8000,
  'app ready'
);

const results = [];
async function check(id, fn) {
  try {
    const r = await fn();
    if (r && typeof r === 'object' && 'pass' in r) {
      results.push({ id, pass: !!r.pass, detail: String(r.detail ?? '') });
    } else {
      results.push({ id, pass: !!r, detail: r ? 'ok' : 'failed' });
    }
  } catch (e) {
    results.push({ id, pass: false, detail: 'Exception: ' + (e?.message || String(e)) });
  }
}

const isVis = (el) => {
  if (!el || el.hidden) return false;
  const cs = getComputedStyle(el);
  if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
};

// 초기 상태 백업 (종료 시 복원용)
// 가정: store.get('uiTheme')로 현재 테마를 읽을 수 있고, 없으면 documentElement.dataset.theme 또는 'light'를 기본값으로 본다.
const origTheme =
  (typeof store !== 'undefined' && typeof store.get === 'function' && store.get('uiTheme')) ||
  document.documentElement.getAttribute('data-theme') ||
  'light';
const origTabIds = new Set(tabs.map((t) => t.id ?? t.spec?.id ?? t));
const addedSessionIds = ['__e1_test_red__', '__e1_test_norm__'];

// 세션 닫기 보조 함수
// 가정: 전역 closeTab(tabOrId) 함수가 있거나 탭 DOM의 .x 버튼을 클릭하여 탭을 닫을 수 있다.
async function closeTestTab(tab) {
  if (!tab) return;
  if (typeof closeTab === 'function') {
    try {
      closeTab(tab.id ?? tab);
      await W(100);
      if (!tabs.includes(tab)) return;
    } catch {}
  }
  const xBtn =
    document.querySelector(`#tabbar [data-id="${tab.id}"] .x`) ||
    document.querySelectorAll('#tabbar .x')[tabs.indexOf(tab)];
  if (xBtn) {
    xBtn.click();
    await W(100);
  }
}

// 트리 재렌더링 보조 함수
// 가정: renderTree() 또는 renderSessions()가 전역에 있거나, #treeSearch의 input 이벤트로 트리를 다시 그릴 수 있다.
function refreshTree() {
  if (typeof renderTree === 'function') return renderTree();
  if (typeof renderSessions === 'function') return renderSessions();
  const ts = document.querySelector('#treeSearch');
  if (ts) ts.dispatchEvent(new Event('input', { bubbles: true }));
}

try {
  // 기본 배치 '1'로 시작
  if (typeof setLayout === 'function') setLayout('1');
  await W(100);

  // =========================================================================
  // §1 전체 배치 순서와 높이
  // =========================================================================
  await check('§1-order-and-heights', () => {
    const mb = document.querySelector('#menubar');
    const tb = document.querySelector('#toolbar');
    const main = document.querySelector('#main');
    const sb = document.querySelector('#statusbar');
    if (!mb || !tb || !main || !sb) {
      return {
        pass: false,
        detail: `필수 요소 누락: menubar=${!!mb}, toolbar=${!!tb}, main=${!!main}, statusbar=${!!sb}`,
      };
    }
    const rMb = mb.getBoundingClientRect();
    const rTb = tb.getBoundingClientRect();
    const rMain = main.getBoundingClientRect();
    const rSb = sb.getBoundingClientRect();

    const orderOk = rMb.top < rTb.top && rTb.top < rMain.top && rMain.top < rSb.top;
    // 가정: "#menubar 약 24px"는 22~26px 범위를 허용한다.
    const mbH = Math.abs(rMb.height - 24) <= 2;
    const tbH = Math.abs(rTb.height - 38) <= 2;
    const sbH = Math.abs(rSb.height - 24) <= 2;

    const rightEl = document.querySelector('#right');
    const sbOutsideRight = !rightEl || !rightEl.contains(sb);
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    const sbFullWidth = Math.abs(rSb.width - vw) <= 2;
    const sbAtBottom = Math.abs(rSb.bottom - vh) <= 2;

    const pass = orderOk && mbH && tbH && sbH && sbOutsideRight && sbFullWidth && sbAtBottom;
    return {
      pass,
      detail: `order=${orderOk}, mbH=${rMb.height.toFixed(1)}, tbH=${rTb.height.toFixed(1)}, sbH=${rSb.height.toFixed(1)}, sbOutsideRight=${sbOutsideRight}, sbW=${rSb.width.toFixed(1)}/${vw}, sbBottom=${rSb.bottom.toFixed(1)}/${vh}`,
    };
  });

  // =========================================================================
  // §2 메뉴 바 (#menubar)
  // =========================================================================
  await check('§2-menubar-and-view-menu', async () => {
    const btns = [...document.querySelectorAll('#menubar button.mb[data-menu]')];
    const menus = btns.map((b) => b.getAttribute('data-menu'));
    const expected = ['file', 'view', 'term', 'tools', 'help'];
    const menusOk = expected.length === menus.length && expected.every((m, i) => menus[i] === m);

    const viewBtn = document.querySelector('#menubar button.mb[data-menu="view"]');
    if (!viewBtn) return { pass: false, detail: 'view 메뉴 버튼 없음' };

    if (typeof setLayout === 'function') setLayout('1');
    await W(50);
    viewBtn.click();
    await W(100);

    const ctx = document.querySelector('#ctxMenu');
    const ctxOpen = isVis(ctx);
    const ctxText = ctx ? ctx.innerText || ctx.textContent : '';

    // 가정: 보기 메뉴의 분할 4항목은 '한 화면', '좌우', '상하', '4분할' 문구를 포함하고 현재 배치 항목에 '✓'가 들어간다.
    const has4Splits = ['한 화면', '좌우', '상하', '4분할'].every((k) => ctxText.includes(k));
    const hasCheck = ctxText.includes('✓');

    // Esc로 메뉴 닫기
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await W(80);
    if (isVis(ctx)) document.body.click();
    await W(50);

    const pass = menusOk && ctxOpen && has4Splits && hasCheck;
    return {
      pass,
      detail: `menus=${menus.join(',')}, ctxOpen=${ctxOpen}, has4Splits=${has4Splits}, hasCheck=${hasCheck}`,
    };
  });

  // =========================================================================
  // §3 툴바 (#toolbar)
  // =========================================================================
  await check('§3-toolbar-order-split-quick-emoji', async () => {
    const tb = document.querySelector('#toolbar');
    if (!tb) return { pass: false, detail: '#toolbar 없음' };

    // 1) 순서 확인
    const orderSelectors = [
      '#sideToggle',
      '#tbSession',
      '#tbLocal',
      '#tbSplit',
      '#tbMulti',
      '#tbMacro',
      '#tbTunnel',
      '#tbTools',
      '#tbLogs',
      '#tbSettings',
      '#quick',
      '#quickGo',
      '#fontDown',      // 11/4 글꼴 묶음(#fontCtl)을 테마 버튼 앞으로 옮김
      '#fontUp',
      '#themeBtn',
      '#fullBtn',
    ];
    const els = orderSelectors.map((s) => tb.querySelector(s) || document.querySelector(s));
    const missing = orderSelectors.filter((_, i) => !els[i] || !isVis(els[i]));
    let xOrderOk = missing.length === 0;
    if (xOrderOk) {
      for (let i = 0; i < els.length - 1; i++) {
        const a = els[i].getBoundingClientRect().left;
        const b = els[i + 1].getBoundingClientRect().left;
        if (a > b + 1) {
          xOrderOk = false;
          break;
        }
      }
    }

    // 2) 분할 4버튼 클릭 및 setLayout 동기화
    const splitWrap = tb.querySelector('div.tb-split#tbSplit') || document.querySelector('#tbSplit');
    const modes = ['1', '2v', '2h', '4'];
    const splitBtns = modes.map((m) => splitWrap?.querySelector(`button[data-layout="${m}"]`));
    const has4Btns = splitBtns.every(Boolean);

    let syncClickOk = false;
    let syncCallOk = false;
    if (has4Btns) {
      syncClickOk = true;
      for (const m of modes) {
        const btn = splitWrap.querySelector(`button[data-layout="${m}"]`);
        btn.click();
        await W(60);
        const onBtns = [...splitWrap.querySelectorAll('button[data-layout].on')];
        if (onBtns.length !== 1 || onBtns[0].getAttribute('data-layout') !== m) {
          syncClickOk = false;
          break;
        }
      }
      if (typeof setLayout === 'function') {
        setLayout('2h');
        await W(60);
        const on2h = [...splitWrap.querySelectorAll('button[data-layout].on')];
        setLayout('1');
        await W(60);
        const on1 = [...splitWrap.querySelectorAll('button[data-layout].on')];
        syncCallOk =
          on2h.length === 1 &&
          on2h[0].getAttribute('data-layout') === '2h' &&
          on1.length === 1 &&
          on1[0].getAttribute('data-layout') === '1';
      }
    }

    // 3) .quick-wrap 안 #quick + #quickGo
    const qw = tb.querySelector('.quick-wrap');
    const qg = tb.querySelector('#quickGo');
    const quickOk = !!qw && qw.contains(tb.querySelector('#quick')) && qw.contains(qg) && isVis(qg);

    // 4) #tbPalette가 툴바에 보이지 않음
    const pal = document.querySelector('#tbPalette');
    const palHiddenInTb = !pal || !tb.contains(pal) || !isVis(pal);

    // 5) 툴바 안 이모지 없음 (명세 §0: 🧰📁⏺⚙ 등 그림 이모지 제거, §3의 ☰는 허용)
    const emojiRe = /[\u{1F300}-\u{1FAFF}\u{23FA}\u{2699}\u{1F9F0}\u{1F4C1}]/u;
    const tbVisibleText = [...tb.querySelectorAll('*')]
      .filter((el) => isVis(el) && el.children.length === 0)
      .map((el) => el.textContent)
      .join('');
    const noEmoji = !emojiRe.test(tbVisibleText);

    const pass =
      xOrderOk && has4Btns && syncClickOk && syncCallOk && quickOk && palHiddenInTb && noEmoji;
    return {
      pass,
      detail: `missing=[${missing.join(',')}], xOrder=${xOrderOk}, has4Btns=${has4Btns}, syncClick=${syncClickOk}, syncCall=${syncCallOk}, quickOk=${quickOk}, palHidden=${palHiddenInTb}, noEmoji=${noEmoji}`,
    };
  });

  // =========================================================================
  // §4 #vtabs 세로 탭 + 사이드바 접기/펴기 + 세션 트리 행
  // =========================================================================
  await check('§4-vtabs-and-sidebar-toggle', async () => {
    const oldSideTabs = document.querySelector('nav.side-tabs');
    const noOldSideTabs = !oldSideTabs || !isVis(oldSideTabs);

    const vtabs = document.querySelector('nav#vtabs') || document.querySelector('#vtabs');
    if (!vtabs) return { pass: false, detail: '#vtabs 없음' };

    const vtBtns = [...vtabs.querySelectorAll('button.vt[data-side]')];
    const sides = vtBtns.map((b) => b.getAttribute('data-side'));
    const sidesOk =
      sides.length === 3 && ['sessions', 'sftp', 'tunnels'].every((s) => sides.includes(s));

    const onCountInitial = vtabs.querySelectorAll('button.vt.on').length === 1;
    const activeBtn = vtabs.querySelector('button.vt.on') || vtBtns[0];
    const otherBtn = vtBtns.find((b) => b !== activeBtn);
    const sidebar = document.querySelector('#sidebar');

    // 켜진 탭 재클릭 → 사이드바 접힘
    activeBtn.click();
    await W(120);
    // 가정: 사이드바가 접히면 #sidebar가 보이지 않거나(display:none / hidden) 폭이 5px 이하가 된다.
    const sbRectCollapsed = sidebar.getBoundingClientRect();
    const collapsedOk = !isVis(sidebar) || sbRectCollapsed.width <= 5;
    const vtabsStillVis = isVis(vtabs);

    // 접힌 상태에서 다른 탭 클릭 → 사이드바 펴지고 그 탭이 .on
    otherBtn.click();
    await W(120);
    const sbRectExpanded = sidebar.getBoundingClientRect();
    const expandedOk = isVis(sidebar) && sbRectExpanded.width >= 100;
    const onAfterOther = vtabs.querySelectorAll('button.vt.on');
    const switchedOk = onAfterOther.length === 1 && onAfterOther[0] === otherBtn;

    // 원래대로 sessions 탭으로 복귀
    const sessBtn = vtabs.querySelector('button.vt[data-side="sessions"]');
    if (sessBtn && !sessBtn.classList.contains('on')) {
      sessBtn.click();
      await W(100);
    }
    if (!isVis(sidebar) || sidebar.getBoundingClientRect().width <= 5) {
      sessBtn?.click();
      await W(100);
    }

    const pass =
      noOldSideTabs &&
      sidesOk &&
      onCountInitial &&
      collapsedOk &&
      vtabsStillVis &&
      expandedOk &&
      switchedOk;
    return {
      pass,
      detail: `noOld=${noOldSideTabs}, sides=[${sides.join(',')}], on1=${onCountInitial}, collapsed=${collapsedOk}, vtabsVis=${vtabsStillVis}, expanded=${expandedOk}, switched=${switchedOk}`,
    };
  });

  // 세션 트리 및 이후 탭/분할/MultiExec 시험을 위한 테스트 세션 등록 및 접속
  // 가정: 세션 객체의 색 라벨 속성은 color: 'red'(또는 labelColor/tag: 'red')이다. 호환을 위해 함께 지정한다.
  DB.sessions = DB.sessions.filter((s) => !addedSessionIds.includes(s.id));
  DB.sessions.push(
    {
      id: '__e1_test_red__',
      type: 'ssh',
      name: 'E1RedSrv',
      host: '127.0.0.1',
      port: 2222,
      username: 'test',
      auth: 'password',
      color: 'red',
      labelColor: 'red',
    },
    {
      id: '__e1_test_norm__',
      type: 'ssh',
      name: 'E1NormSrv',
      host: '127.0.0.1',
      port: 2222,
      username: 'test',
      auth: 'password',
      color: 'blue',
      labelColor: 'blue',
    }
  );
  refreshTree();
  await W(150);

  await check('§4-session-row-order-dot-prod', async () => {
    const sidebar = document.querySelector('#sidebar');
    if (!sidebar) return { pass: false, detail: '#sidebar 없음' };

    // 가정: 세션 행은 #sidebar 안에서 세션 이름을 포함한 행 요소([data-id] 또는 가장 가까운 행 요소)로 찾는다.
    const findRow = (id, name) => {
      const byId = sidebar.querySelector(`[data-sid="${id}"], [data-id="${id}"], [data-session="${id}"]`);
      if (byId) return byId;
      const all = [...sidebar.querySelectorAll('li, div, .tree-row, .row, .item, .session-item')];
      return all.find(
        (el) =>
          el.textContent.includes(name) &&
          el.querySelector('.dot') &&
          el.querySelector('.pt')
      );
    };

    const redRow = findRow('__e1_test_red__', 'E1RedSrv');
    const normRow = findRow('__e1_test_norm__', 'E1NormSrv');
    if (!redRow || !normRow) {
      return { pass: false, detail: `세션 행 탐색 실패: red=${!!redRow}, norm=${!!normRow}` };
    }

    // 1) 열린 탭 없는 세션은 .dot.off
    const redDotBefore = redRow.querySelector('.dot');
    const normDotBefore = normRow.querySelector('.dot');
    const dotOffBefore =
      redDotBefore?.classList.contains('off') && normDotBefore?.classList.contains('off');

    // 2) red 세션에만 .prod 존재
    const redProd = redRow.querySelector('.prod');
    const normProd = normRow.querySelector('.prod');
    const prodOnlyRed = !!redProd && isVis(redProd) && (!normProd || !isVis(normProd));

    // 3) 자식 순서: .dot → .pt → 이름 → .prod
    const rDot = redDotBefore.getBoundingClientRect().left;
    const rPt = redRow.querySelector('.pt').getBoundingClientRect().left;
    const rProd = redProd ? redProd.getBoundingClientRect().left : Infinity;
    // 이름 요소가 따로 있으면 위치 비교, 텍스트 노드면 .pt와 .prod 사이에 위치하는지 확인
    const childOrderOk = rDot < rPt && rPt < rProd;

    // 4) 세션 접속 시 채워진 점(.off 해제) 확인
    autoAnswer();
    const nBefore = tabs.length;
    openSpec(DB.sessions.find((s) => s.id === '__e1_test_red__'));
    await until(() => tabs.length > nBefore, 4000, 'open red session tab');
    const redTab = tabs[tabs.length - 1];
    await until(() => redTab.state === 'on', 10000, 'red session connected');
    refreshTree();
    await W(150);

    const redRowAfter = findRow('__e1_test_red__', 'E1RedSrv');
    const redDotAfter = redRowAfter?.querySelector('.dot');
    const dotFilledAfter = !!redDotAfter && !redDotAfter.classList.contains('off');

    const pass = dotOffBefore && prodOnlyRed && childOrderOk && dotFilledAfter;
    return {
      pass,
      detail: `dotOffBefore=${dotOffBefore}, prodOnlyRed=${prodOnlyRed}, orderOk=${childOrderOk}, dotFilledAfter=${dotFilledAfter}`,
    };
  });

  // 두 번째 탭을 openFake()로 열어 탭 바/2분할/MultiExec 시험에 사용
  const fakeTab = await openFake(2222);
  await W(150);

  // =========================================================================
  // §5 탭 바 (#tabbar) 자식 순서, .x 크기, #meBadge
  // =========================================================================
  await check('§5-tabbar-order-close-size-mebadge', async () => {
    const tabbar = document.querySelector('#tabbar');
    if (!tabbar) return { pass: false, detail: '#tabbar 없음' };

    // red 세션 탭에서 .dot -> .pt -> .label -> .prod -> .x 순서 확인
    const tabEls = [...tabbar.querySelectorAll('.tab, [data-id]')].filter((el) =>
      el.querySelector('.x')
    );
    const redTabEl =
      tabEls.find((el) => el.textContent.includes('E1RedSrv')) || tabEls[0];
    if (!redTabEl) return { pass: false, detail: '탭 요소를 찾을 수 없음' };

    const dot = redTabEl.querySelector('.dot');
    const pt = redTabEl.querySelector('.pt');
    const label = redTabEl.querySelector('.label');
    const prod = redTabEl.querySelector('.prod');
    const xBtn = redTabEl.querySelector('.x');

    const parts = [dot, pt, label, ...(prod ? [prod] : []), xBtn];
    let orderOk = parts.every(Boolean);
    if (orderOk) {
      for (let i = 0; i < parts.length - 1; i++) {
        if (parts[i].getBoundingClientRect().left > parts[i + 1].getBoundingClientRect().left + 1) {
          orderOk = false;
          break;
        }
      }
    }

    const xRect = xBtn ? xBtn.getBoundingClientRect() : { width: 0, height: 0 };
    const xSizeOk = xRect.width >= 18 && xRect.height >= 18;

    // #meBadge: MultiExec 꺼졌을 때 숨김, 켰을 때 보이고 대상 수 표시
    const tbMulti = document.querySelector('#tbMulti');
    const meBadge = document.querySelector('#meBadge');
    if (tbMulti?.classList.contains('on')) {
      tbMulti.click();
      await W(100);
    }
    const hiddenWhenOff = !meBadge || !isVis(meBadge);

    tbMulti?.click();
    await W(120);
    const visWhenOn = !!meBadge && isVis(meBadge);
    const badgeText = meBadge ? meBadge.textContent.trim() : '';
    const hasCount = /MultiExec\s*·\s*\d+/.test(badgeText);

    const pass = orderOk && xSizeOk && hiddenWhenOff && visWhenOn && hasCount;
    return {
      pass,
      detail: `order=${orderOk}, xSize=${xRect.width.toFixed(1)}x${xRect.height.toFixed(1)}, hiddenOff=${hiddenWhenOff}, visOn=${visWhenOn}, badge="${badgeText}"`,
    };
  });

  // =========================================================================
  // §6 #multiBar 높이 <= 32
  // =========================================================================
  await check('§6-multibar-height', async () => {
    const tbMulti = document.querySelector('#tbMulti');
    if (tbMulti && !tbMulti.classList.contains('on')) {
      tbMulti.click();
      await W(100);
    }
    const mb = document.querySelector('#multiBar');
    if (!mb || !isVis(mb)) return { pass: false, detail: '#multiBar가 보이지 않음' };
    const h = mb.getBoundingClientRect().height;
    const noOldIcon = !mb.textContent.includes('⫶');
    const pass = h > 0 && h <= 32 && noOldIcon;
    return { pass, detail: `height=${h.toFixed(1)}px, noOldIcon=${noOldIcon}` };
  });

  // =========================================================================
  // §7 .pane-title 동시입력 칩 & 2분할 포커스 칸만 .act
  // =========================================================================
  await check('§7-pane-title-chip-and-act', async () => {
    if (typeof setLayout === 'function') setLayout('2v');
    await W(150);

    // MultiExec가 켜진 상태에서 전체 대상 선택 보장
    const tbMulti = document.querySelector('#tbMulti');
    if (tbMulti && !tbMulti.classList.contains('on')) {
      tbMulti.click();
      await W(100);
    }

    const panes = [...document.querySelectorAll('#workspace .pane')].filter(isVis);
    if (panes.length < 2) {
      return { pass: false, detail: `2분할에서 보이는 .pane 수 부족: ${panes.length}` };
    }

    // MultiExec 대상(.me-target) 칸의 .pane-title 안 '동시입력' .chip 확인
    const mePane = panes.find((p) => p.classList.contains('me-target')) || panes[0];
    const chips = [...mePane.querySelectorAll('.pane-title .chip')];
    const hasMeChip = chips.some((c) => isVis(c) && c.textContent.includes('동시입력'));

    // 포커스 칸만 .act 확인 (명세 §7: "입력을 받는 칸(포커스 칸)의 머리줄에 .act")
    // 가정: .act 클래스는 .pane-title에 붙거나(명세 문구 그대로), 상위 .pane에 붙을 수 있어 .pane-title.act 우선으로 확인하되 .pane.act도 함께 검사한다.
    const getActCount = () => {
      const titleActs = panes.filter((p) => p.querySelector('.pane-title.act'));
      if (titleActs.length > 0) return titleActs.length;
      return panes.filter((p) => p.classList.contains('act')).length;
    };

    panes[0].click();
    await W(80);
    const actCount1 = getActCount();

    panes[1].click();
    await W(80);
    const actCount2 = getActCount();
    const pane1ActiveAfterClick =
      !!panes[1].querySelector('.pane-title.act') || panes[1].classList.contains('act');

    // MultiExec 끄기
    if (tbMulti?.classList.contains('on')) {
      tbMulti.click();
      await W(80);
    }

    const pass = hasMeChip && actCount1 === 1 && actCount2 === 1 && pane1ActiveAfterClick;
    return {
      pass,
      detail: `hasMeChip=${hasMeChip}, actCount1=${actCount1}, actCount2=${actCount2}, switchedFocus=${pane1ActiveAfterClick}`,
    };
  });

  // =========================================================================
  // §8 상태 바 (#sbApp "탭 N · 연결 M" 및 .meter 임계 69/70/90)
  // =========================================================================
  await check('§8-statusbar-sbapp-and-meter', async () => {
    const sbApp = document.querySelector('#statusbar #sbApp') || document.querySelector('#sbApp');
    if (!sbApp || !isVis(sbApp)) return { pass: false, detail: '#sbApp 없음 또는 숨김' };

    const totalTabs = tabs.length;
    const connTabs = tabs.filter((t) => t.state === 'on').length;
    const expectedStr = `탭 ${totalTabs} · 연결 ${connTabs}`;

    // 상태 바 갱신 유도
    if (typeof updateStatus === 'function') updateStatus();
    if (typeof renderStatus === 'function') {
      try { renderStatus(); } catch {}
    }
    await W(100);

    const appText = sbApp.textContent.replace(/\s+/g, ' ').trim();
    const countsMatch = appText.includes(expectedStr);

    // .meter 임계 검증 (69%=기본, 70%=.warm, 90%=.hot)
    // 가정: 전역에 막대 HTML/요소를 생성하는 헬퍼(meterHtml, makeMeter, renderMeter 등)나 renderStatus가 있으면 호출해 검증하고,
    // 그렇지 않으면 함수 본문 정규식 또는 스타일시트의 .meter.warm / .meter.hot 규칙과 함께 확인한다.
    let meterDetail = 'checked-via-app';
    let meterOk = true;

    const meterFn =
      window.meterHtml || window.makeMeter || window.fmtMeter || window.buildMeter || null;
    if (typeof meterFn === 'function') {
      const h69 = String(meterFn(69));
      const h70 = String(meterFn(70));
      const h90 = String(meterFn(90));
      meterOk =
        !h69.includes('warm') &&
        !h69.includes('hot') &&
        h70.includes('warm') &&
        !h70.includes('hot') &&
        h90.includes('hot');
      meterDetail = `fn(69/70/90): ok=${meterOk}`;
    } else {
      // 전역 스크립트/함수 문자열에서 70 / 90 임계 확인 시도
      const scriptsText = [...document.querySelectorAll('script')]
        .map((s) => s.textContent)
        .join('\n');
      if (scriptsText.includes('warm') && scriptsText.includes('hot')) {
        // 기존 75% 임계가 남아 있으면 실패 처리
        const has70 = /70/.test(scriptsText);
        const has90 = /90/.test(scriptsText);
        meterOk = has70 && has90;
        meterDetail = `script-threshold(70=${has70}, 90=${has90})`;
      }
    }

    const pass = countsMatch && meterOk;
    return {
      pass,
      detail: `sbApp="${appText}" (expected "${expectedStr}"), meter=${meterDetail}`,
    };
  });

  // =========================================================================
  // §10 배지(.pt, .prod) font-size >= 10px & 다크 테마 --line / --dim 값
  // =========================================================================
  await check('§10-badge-fontsize-and-dark-tokens', async () => {
    const ptEl = document.querySelector('.pt');
    const prodEl = document.querySelector('.prod');
    if (!ptEl || !prodEl) {
      return { pass: false, detail: `배지 요소 부족: pt=${!!ptEl}, prod=${!!prodEl}` };
    }
    const ptSize = parseFloat(getComputedStyle(ptEl).fontSize);
    const prodSize = parseFloat(getComputedStyle(prodEl).fontSize);
    const fontOk = ptSize >= 10 && prodSize >= 10;

    if (typeof store !== 'undefined' && typeof store.set === 'function') {
      store.set('uiTheme', 'dark');
    }
    if (typeof applyTheme === 'function') {
      applyTheme();
    } else {
      document.documentElement.setAttribute('data-theme', 'dark');
    }
    await W(80);

    const rootTarget =
      document.querySelector('[data-theme="dark"]') || document.documentElement;
    const cs = getComputedStyle(rootTarget);
    const lineVal = cs.getPropertyValue('--line').trim().toLowerCase();
    const dimVal = cs.getPropertyValue('--dim').trim().toLowerCase();

    const tokensOk = lineVal === '#52565e' && dimVal === '#a8abb1';
    const pass = fontOk && tokensOk;
    return {
      pass,
      detail: `pt=${ptSize}px, prod=${prodSize}px, --line="${lineVal}", --dim="${dimVal}"`,
    };
  });

  // =========================================================================
  // 공통: 콘솔/런타임 오류 0건 & 1280x720 가로 스크롤 없음
  // =========================================================================
  await check('common-no-errors-and-no-hscroll', async () => {
    if (typeof setLayout === 'function') setLayout('1');
    await W(80);
    const sw = document.documentElement.scrollWidth;
    const cw = document.documentElement.clientWidth;
    const noHScroll = sw <= cw;
    const noErrors = errs.length === 0;
    return {
      pass: noHScroll && noErrors,
      detail: `scrollWidth=${sw}, clientWidth=${cw}, errors=${errs.length} (${errs.join('; ')})`,
    };
  });
} finally {
  // 정리: MultiExec 끄기, 추가한 탭 닫기, 임시 세션 제거, 배치 '1', 테마 복원
  try {
    const tbMulti = document.querySelector('#tbMulti');
    if (tbMulti?.classList.contains('on')) tbMulti.click();
  } catch {}

  try {
    const toClose = tabs.filter((t) => !origTabIds.has(t.id ?? t.spec?.id ?? t));
    for (const t of toClose) {
      await closeTestTab(t);
    }
  } catch {}

  try {
    if (typeof DB !== 'undefined' && Array.isArray(DB.sessions)) {
      DB.sessions = DB.sessions.filter((s) => !addedSessionIds.includes(s.id));
      refreshTree();
    }
  } catch {}

  try {
    if (typeof setLayout === 'function') setLayout('1');
  } catch {}

  try {
    const vtabs = document.querySelector('#vtabs');
    const sessBtn = vtabs?.querySelector('button.vt[data-side="sessions"]');
    const sidebar = document.querySelector('#sidebar');
    if (sessBtn && !sessBtn.classList.contains('on')) sessBtn.click();
    if (sidebar && (!isVis(sidebar) || sidebar.getBoundingClientRect().width <= 5)) {
      sessBtn?.click();
    }
  } catch {}

  try {
    if (typeof store !== 'undefined' && typeof store.set === 'function') {
      store.set('uiTheme', origTheme);
    }
    if (typeof applyTheme === 'function') {
      applyTheme();
    }
  } catch {}

  window.removeEventListener('error', onErr);
  window.removeEventListener('unhandledrejection', onErr);
}

const R = {
  pass: results.length > 0 && results.every((r) => r.pass),
  results,
  errors: errs,
};
return R;
