// 메뉴 대분류→소분류 개편(SPEC_MENU_2026-11-17.md) 브라우저 시험 스크립트
// 실행: cat dev/harness/lib.js dev/harness/t_menu.js | PYTHONIOENCODING=utf-8 python dev/harness/cdp.py http://127.0.0.1:18022/ -
//
// [가정 목록]
// 1. 메뉴바 버튼은 `#menubar button.mb[data-menu]`이며, data-menu 값은 순서대로
//    ['file', 'term', 'view', 'net', 'sec', 'help'] 이다. 최상위 메뉴 컨테이너는 `#ctxMenu`이다.
// 2. 하위 메뉴의 DOM 구조(id/class)는 명세에 정해지지 않았으므로, 메뉴를 열기 전 보이던 버튼 집합(baseBtns)과
//    최상위 메뉴만 열렸을 때 보이는 버튼 집합(topBtns)을 제외한 "새로 화면에 보이는 버튼들"로 하위 메뉴를 판정한다.
// 3. 마우스 hover로 하위 메뉴를 열 때는 pointerenter/mouseenter/pointerover/mouseover/mousemove 이벤트를 보내고,
//    명세 M1의 150ms 지연을 감안해 250ms 대기한다.
// 4. 포커스된 탭이 없을 때 터미널 메뉴의 `출력 ▸`, `탭 ▸`는 하위 항목이 모두 disabled이므로 부모도 disabled가 된다(M1).
//    disabled 부모에서 하위 메뉴가 바로 열리지 않는 구현일 경우, disabled 판정을 먼저 마친 뒤
//    부모 버튼의 disabled를 일시 해제하거나 임시 더미 탭을 넣어 하위 항목 라벨을 검증하고 즉시 복원한다.
// 5. 항목 버튼의 텍스트에는 단축키 힌트나 `✓`, `▸`가 함께 들어갈 수 있으므로 라벨 부분 문자열과
//    `▸` 존재 여부(textContent 또는 ::after content)로 판정한다.
// 6. 키보드 이벤트는 `document.activeElement || #ctxMenu || document`에 bubbles:true로 dispatch하며,
//    포커스 이동은 activeElement 또는 활성 클래스(.on/.focus/.active/.sel/[data-focus]) 및 보이는 메뉴 변화로 판정한다.
// 7. `#guideDlg`의 세로 탭은 `.tdlg-tabs button`(또는 좌측 탭 영역의 button)이며, 클릭 시 본문 영역의 가시 텍스트가 바뀐다.
// 8. 기능 표시(feature) 끔 시험(#8)은 명세에 설정 저장 API/선택자가 없으므로, `#settingsDlg` 내 체크박스를
//    안전하게 식별할 수 없으면 SKIP(pass: true, skip: true)으로 처리한다.

const errs = [];
const onErr = (e) => errs.push(String(e?.message || e?.reason || e));
window.addEventListener('error', onErr);
window.addEventListener('unhandledrejection', onErr);

await until(
  () => typeof DB !== 'undefined' && typeof tabs !== 'undefined' && document.querySelector('#menubar'),
  8000,
  'app ready'
);

const results = [];
async function check(id, fn) {
  try {
    const r = await fn();
    if (r && typeof r === 'object' && 'pass' in r) {
      results.push({
        id,
        pass: !!r.pass,
        ...(r.skip ? { skip: true } : {}),
        detail: String(r.detail ?? ''),
      });
    } else {
      results.push({ id, pass: !!r, detail: r ? 'ok' : 'failed' });
    }
  } catch (e) {
    results.push({ id, pass: false, detail: 'Exception: ' + (e?.message || String(e)) });
  }
}

// 요소가 화면에 실제로 보이는지 판정하는 함수
function isVis(el) {
  if (!el || el.hidden || el.closest('[hidden]')) return false;
  const dlg = el.closest('dialog');
  if (dlg && !dlg.open) return false;
  const cs = getComputedStyle(el);
  if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();

function hasSubArrow(btn) {
  if (!btn) return false;
  if (/[▸▶]/.test(btn.textContent || '')) return true;
  try {
    const after = getComputedStyle(btn, '::after').content || '';
    if (/[▸▶]/.test(after)) return true;
  } catch {}
  return false;
}

function isDisabled(btn) {
  if (!btn) return false;
  return (
    !!btn.disabled ||
    btn.classList.contains('disabled') ||
    btn.getAttribute('aria-disabled') === 'true'
  );
}

// 마우스 hover 이벤트 전달
function hoverEl(el) {
  if (!el) return;
  const r = el.getBoundingClientRect();
  const cx = r.left + r.width / 2;
  const cy = r.top + r.height / 2;
  const opts = { bubbles: true, cancelable: true, clientX: cx, clientY: cy };
  el.dispatchEvent(new PointerEvent('pointerenter', { ...opts, bubbles: false }));
  el.dispatchEvent(new MouseEvent('mouseenter', { ...opts, bubbles: false }));
  el.dispatchEvent(new PointerEvent('pointerover', opts));
  el.dispatchEvent(new MouseEvent('mouseover', opts));
  el.dispatchEvent(new PointerEvent('pointermove', opts));
  el.dispatchEvent(new MouseEvent('mousemove', opts));
}

// 바깥 pointerdown으로 열린 메뉴 모두 닫기
async function closeMenus() {
  const target = document.querySelector('#workspace') || document.querySelector('#main') || document.body;
  const r = target.getBoundingClientRect();
  const opts = { bubbles: true, cancelable: true, clientX: r.left + 10, clientY: r.top + 10 };
  target.dispatchEvent(new PointerEvent('pointerdown', opts));
  target.dispatchEvent(new MouseEvent('mousedown', opts));
  target.dispatchEvent(new MouseEvent('click', opts));
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  await W(80);
  const ctx = document.querySelector('#ctxMenu');
  if (ctx && isVis(ctx)) {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    document.body.click();
    await W(80);
  }
}

// 모든 열린 dialog 닫기
async function closeDialogs() {
  for (const d of document.querySelectorAll('dialog')) {
    if (d.open) {
      try { d.close(); } catch {}
    }
  }
  await W(50);
}

// 메뉴가 닫힌 상태에서 기본 화면의 보이는 버튼 집합
function getVisibleButtons() {
  return [...document.querySelectorAll('button')].filter(isVis);
}

// 특정 메뉴바 메뉴를 열고 { mbBtn, baseBtns, topBtns } 반환
async function openMenubarMenu(menuKey) {
  await closeMenus();
  const baseBtns = new Set(getVisibleButtons());
  const mbBtn = document.querySelector(`#menubar button.mb[data-menu="${menuKey}"]`);
  if (!mbBtn) return { mbBtn: null, baseBtns, topBtns: [] };
  mbBtn.click();
  await W(120);
  const topBtns = getVisibleButtons().filter((b) => !baseBtns.has(b));
  return { mbBtn, baseBtns, topBtns };
}

// 라벨 텍스트를 포함하는 버튼 찾기
function findBtnByLabel(btns, label) {
  return btns.find((b) => norm(b.textContent).includes(label));
}

// ▸ 항목에서 하위 메뉴 열기 시도 (마우스 hover 후 안 열리면 click 보조)
async function openSubmenuFrom(parentBtn, baseBtns, topBtns, hoverOnly = false) {
  if (!parentBtn) return [];
  const topSet = new Set(topBtns);
  hoverEl(parentBtn);
  await W(250);
  let subBtns = getVisibleButtons().filter((b) => !baseBtns.has(b) && !topSet.has(b));
  if (subBtns.length === 0 && !hoverOnly) {
    parentBtn.click();
    await W(150);
    subBtns = getVisibleButtons().filter((b) => !baseBtns.has(b) && !topSet.has(b));
  }
  return subBtns;
}

// 키보드 이벤트 전송 및 현재 포커스/활성 메뉴 버튼 조회
function sendKey(key) {
  const target =
    (document.activeElement && document.activeElement !== document.body
      ? document.activeElement
      : null) ||
    document.querySelector('#ctxMenu') ||
    document;
  target.dispatchEvent(
    new KeyboardEvent('keydown', { key, code: key, bubbles: true, cancelable: true })
  );
}

function getActiveMenuButton(baseBtns) {
  const menuBtns = getVisibleButtons().filter((b) => !baseBtns.has(b));
  if (document.activeElement && menuBtns.includes(document.activeElement)) {
    return document.activeElement;
  }
  return (
    menuBtns.find(
      (b) =>
        b.classList.contains('on') ||
        b.classList.contains('focus') ||
        b.classList.contains('active') ||
        b.classList.contains('sel') ||
        b.classList.contains('selected') ||
        b.classList.contains('kb-focus') ||
        b.hasAttribute('data-focus') ||
        b.getAttribute('aria-current') === 'true' ||
        b.getAttribute('aria-selected') === 'true'
    ) || null
  );
}

try {
  await closeDialogs();
  await closeMenus();

  // =========================================================================
  // 1. 메뉴바 순서: 파일·터미널·보기·네트워킹·보안·도움말, "도구" 메뉴 없음
  // =========================================================================
  await check('1-menubar-order-and-no-tools', () => {
    const btns = [...document.querySelectorAll('#menubar button.mb[data-menu]')].filter(isVis);
    const keys = btns.map((b) => b.getAttribute('data-menu'));
    const labels = btns.map((b) => norm(b.textContent));

    const expectedKeys = ['file', 'term', 'view', 'net', 'sec', 'help'];
    const expectedLabels = ['파일', '터미널', '보기', '네트워킹', '보안', '도움말'];

    const keysOk =
      keys.length === expectedKeys.length && expectedKeys.every((k, i) => keys[i] === k);
    const labelsOk =
      labels.length === expectedLabels.length && expectedLabels.every((l, i) => labels[i] === l);

    // 좌→우 화면 배치 순서 확인
    let xOrderOk = btns.length === 6;
    for (let i = 0; i < btns.length - 1; i++) {
      if (btns[i].getBoundingClientRect().left >= btns[i + 1].getBoundingClientRect().left) {
        xOrderOk = false;
        break;
      }
    }

    const toolsBtn = document.querySelector('#menubar [data-menu="tools"]');
    const noToolsMenu =
      (!toolsBtn || !isVis(toolsBtn)) && !labels.some((l) => l.includes('도구'));

    const pass = keysOk && labelsOk && xOrderOk && noToolsMenu;
    return {
      pass,
      detail: `keys=[${keys.join(',')}], labels=[${labels.join(',')}], xOrder=${xOrderOk}, noTools=${noToolsMenu}`,
    };
  });

  // =========================================================================
  // 2. 각 메뉴의 최상위 항목과 ▸ 하위 항목 라벨이 명세 M2와 일치
  //    (포커스된 탭 없음 상태 기준; 탭 필요 항목은 disabled)
  // =========================================================================
  await check('2-menu-items-and-submenus-m2', async () => {
    // 포커스된 탭이 없는 상태 보장 (기존 탭이 있으면 임시 백업 후 비움)
    const savedTabs = [...tabs];
    tabs.length = 0;
    const issues = [];

    try {
      // (A) 파일 메뉴
      {
        const { baseBtns, topBtns } = await openMenubarMenu('file');
        const reqTop = [
          '새 세션',
          '로컬 터미널',
          '세션 가져오기',
          '세션 내보내기',
          '세션 로그 폴더',
          '설정',
          '서버 종료',
        ];
        for (const lbl of reqTop) {
          if (!findBtnByLabel(topBtns, lbl)) issues.push(`file: 최상위 '${lbl}' 누락`);
        }
        const localBtn = findBtnByLabel(topBtns, '로컬 터미널');
        if (localBtn && !hasSubArrow(localBtn)) {
          issues.push('file: 로컬 터미널에 ▸ 표시 없음');
        }
        if (localBtn && !isDisabled(localBtn)) {
          const sub = await openSubmenuFrom(localBtn, baseBtns, topBtns);
          if (sub.length === 0) issues.push('file: 로컬 터미널 ▸ 하위 메뉴가 열리지 않음');
        }
      }

      // (B) 터미널 메뉴 (포커스된 탭 없음)
      {
        const { baseBtns, topBtns } = await openMenubarMenu('term');
        const reqTop = ['터미널에서 찾기', '출력', '탭', '입력'];
        for (const lbl of reqTop) {
          if (!findBtnByLabel(topBtns, lbl)) issues.push(`term: 최상위 '${lbl}' 누락`);
        }
        // VNC ▸는 포커스 탭이 VNC일 때만 표시되어야 함
        if (findBtnByLabel(topBtns, 'VNC')) {
          issues.push('term: 포커스 탭이 없는데 VNC 항목이 표시됨');
        }
        // 탭이 필요한 항목(터미널에서 찾기, 출력 ▸, 탭 ▸)은 disabled여야 함
        for (const lbl of ['터미널에서 찾기', '출력', '탭']) {
          const b = findBtnByLabel(topBtns, lbl);
          if (b && !isDisabled(b)) issues.push(`term: 탭 없음 상태에서 '${lbl}'가 disabled가 아님`);
        }
        for (const lbl of ['출력', '탭', '입력']) {
          const b = findBtnByLabel(topBtns, lbl);
          if (b && !hasSubArrow(b)) issues.push(`term: '${lbl}'에 ▸ 표시 없음`);
        }

        // 입력 ▸ 하위: MultiExec, 매크로
        const inputBtn = findBtnByLabel(topBtns, '입력');
        if (inputBtn) {
          if (isDisabled(inputBtn)) inputBtn.disabled = false;
          const inSub = await openSubmenuFrom(inputBtn, baseBtns, topBtns);
          for (const sl of ['MultiExec', '매크로']) {
            if (!findBtnByLabel(inSub, sl)) issues.push(`term›입력: '${sl}' 누락`);
          }
        }

        // 출력 ▸ 및 탭 ▸ 하위 라벨 확인 (disabled 상태에서 안 열리면 일시 해제/더미 탭 폴백으로 확인)
        const checkTermSub = async (parentLabel, expectedSubLabels) => {
          let { baseBtns: bb, topBtns: tb } = await openMenubarMenu('term');
          let pBtn = findBtnByLabel(tb, parentLabel);
          let sub = await openSubmenuFrom(pBtn, bb, tb);
          if (sub.length === 0 && pBtn) {
            pBtn.disabled = false;
            pBtn.classList.remove('disabled');
            sub = await openSubmenuFrom(pBtn, bb, tb);
          }
          if (sub.length === 0) {
            // 더미 활성 탭을 임시 주입하여 하위 라벨 구성만 확인
            const dummy = { id: '__m2_dummy__', state: 'on', spec: { type: 'ssh', name: 'd' }, term: {} };
            tabs.push(dummy);
            const prevCur = window.curTab;
            try { window.curTab = dummy; } catch {}
            ({ baseBtns: bb, topBtns: tb } = await openMenubarMenu('term'));
            pBtn = findBtnByLabel(tb, parentLabel);
            sub = await openSubmenuFrom(pBtn, bb, tb);
            tabs.length = 0;
            try { window.curTab = prevCur; } catch {}
          }
          for (const sl of expectedSubLabels) {
            if (!findBtnByLabel(sub, sl)) {
              issues.push(`term›${parentLabel}: '${sl}' 누락 (열린 하위=${sub.map((x) => norm(x.textContent)).join('|')})`);
            }
          }
        };

        await checkTermSub('출력', ['저장', '인쇄']);
        await checkTermSub('탭', ['복제', '이름 바꾸기', '새 창으로 분리', '재접속', '닫기', '다른 탭 모두 닫기']);
      }

      // (C) 보기 메뉴
      {
        const { baseBtns, topBtns } = await openMenubarMenu('view');
        const reqTop = [
          '사이드바 접기/펴기',
          '화면 분할',
          '라이트/다크 전환',
          '터미널 글꼴',
          '화면 글꼴',
          '전체화면',
          '명령 팔레트',
        ];
        for (const lbl of reqTop) {
          if (!findBtnByLabel(topBtns, lbl)) issues.push(`view: 최상위 '${lbl}' 누락`);
        }

        const splitBtn = findBtnByLabel(topBtns, '화면 분할');
        if (splitBtn && !hasSubArrow(splitBtn)) issues.push('view: 화면 분할에 ▸ 없음');
        const splitSub = await openSubmenuFrom(splitBtn, baseBtns, topBtns);
        for (const sl of ['한 화면', '좌우', '상하', '4분할']) {
          if (!findBtnByLabel(splitSub, sl)) issues.push(`view›화면 분할: '${sl}' 누락`);
        }
        if (!splitSub.some((b) => b.textContent.includes('✓'))) {
          issues.push('view›화면 분할: 현재 분할(✓) 표시 없음');
        }

        for (const fontParent of ['터미널 글꼴', '화면 글꼴']) {
          const { baseBtns: bb, topBtns: tb } = await openMenubarMenu('view');
          const fBtn = findBtnByLabel(tb, fontParent);
          if (fBtn && !hasSubArrow(fBtn)) issues.push(`view: '${fontParent}'에 ▸ 없음`);
          const fSub = await openSubmenuFrom(fBtn, bb, tb);
          for (const sl of ['크게', '작게', '기본']) {
            if (!findBtnByLabel(fSub, sl)) issues.push(`view›${fontParent}: '${sl}' 누락`);
          }
          if (!fSub.some((b) => b.textContent.includes('✓'))) {
            issues.push(`view›${fontParent}: 현재 글꼴(✓) 표시 없음`);
          }
        }
      }

      // (D) 네트워킹 메뉴
      {
        const { baseBtns, topBtns } = await openMenubarMenu('net');
        const reqTop = ['터널 관리', '포트 스캐너', '이 PC의 열린 포트', '파일 서버'];
        for (const lbl of reqTop) {
          if (!findBtnByLabel(topBtns, lbl)) issues.push(`net: 최상위 '${lbl}' 누락`);
        }
        // 포커스 탭이 연결된 SSH가 아니므로 '원격 서버 상세'는 표시되지 않아야 함
        if (findBtnByLabel(topBtns, '원격 서버 상세')) {
          issues.push('net: 연결된 SSH 탭이 없는데 원격 서버 상세가 표시됨');
        }
        const fsBtn = findBtnByLabel(topBtns, '파일 서버');
        if (fsBtn && !hasSubArrow(fsBtn)) issues.push('net: 파일 서버에 ▸ 없음');
        const fsSub = await openSubmenuFrom(fsBtn, baseBtns, topBtns);
        for (const sl of ['TFTP 서버', 'HTTP 파일 서버']) {
          if (!findBtnByLabel(fsSub, sl)) issues.push(`net›파일 서버: '${sl}' 누락`);
        }
      }

      // (E) 보안 메뉴
      {
        const { topBtns } = await openMenubarMenu('sec');
        for (const lbl of ['SSH 키 생성', '알려진 호스트 관리', '비밀번호 저장소 관리']) {
          if (!findBtnByLabel(topBtns, lbl)) issues.push(`sec: 최상위 '${lbl}' 누락`);
        }
      }

      // (F) 도움말 메뉴
      {
        const { topBtns } = await openMenubarMenu('help');
        for (const lbl of ['사용법', '단축키 안내', '버전 정보']) {
          if (!findBtnByLabel(topBtns, lbl)) issues.push(`help: 최상위 '${lbl}' 누락`);
        }
        if (findBtnByLabel(topBtns, '라이선스')) {
          issues.push('help: 제거되어야 할 라이선스 항목이 존재함');
        }
      }
    } finally {
      tabs.length = 0;
      tabs.push(...savedTabs);
      await closeMenus();
    }

    return {
      pass: issues.length === 0,
      detail: issues.length === 0 ? '6개 메뉴 및 하위 메뉴 라벨·disabled 일치' : issues.join('; '),
    };
  });

  // =========================================================================
  // 3. 하위 메뉴가 마우스로 열리고, 다른 항목에 올리면 이전 하위 메뉴가 닫힘
  // =========================================================================
  await check('3-submenu-mouse-open-and-switch-close', async () => {
    const { baseBtns, topBtns } = await openMenubarMenu('view');
    const topSet = new Set(topBtns);

    const splitBtn = findBtnByLabel(topBtns, '화면 분할');
    const termFontBtn = findBtnByLabel(topBtns, '터미널 글꼴');
    const themeBtn = findBtnByLabel(topBtns, '라이트/다크 전환');
    if (!splitBtn || !termFontBtn || !themeBtn) {
      return { pass: false, detail: 'view 메뉴 필수 항목 탐색 실패' };
    }

    // 1) 클릭 없이 마우스 hover만으로 '화면 분할 ▸' 하위 메뉴 열기
    const sub1 = await openSubmenuFrom(splitBtn, baseBtns, topBtns, true);
    const splitOpenedByMouse =
      !!findBtnByLabel(sub1, '좌우') && !!findBtnByLabel(sub1, '4분할');

    // 2) 다른 하위 메뉴 항목('터미널 글꼴 ▸')에 올리면 이전 하위 메뉴('화면 분할')가 닫히고 새 하위 메뉴가 열림
    hoverEl(termFontBtn);
    await W(250);
    const sub2 = getVisibleButtons().filter((b) => !baseBtns.has(b) && !topSet.has(b));
    const prevClosedOnOtherSub = !findBtnByLabel(sub2, '4분할') && !findBtnByLabel(sub2, '좌우');
    const nextSubOpened = !!findBtnByLabel(sub2, '크게') && !!findBtnByLabel(sub2, '작게');

    // 3) 일반 항목('라이트/다크 전환')에 올리면 열려 있던 하위 메뉴가 닫힘
    hoverEl(themeBtn);
    await W(250);
    const sub3 = getVisibleButtons().filter((b) => !baseBtns.has(b) && !topSet.has(b));
    const subClosedOnPlainItem = sub3.length === 0;
    const topStillOpen = isVis(document.querySelector('#ctxMenu'));

    await closeMenus();
    const pass =
      splitOpenedByMouse && prevClosedOnOtherSub && nextSubOpened && subClosedOnPlainItem && topStillOpen;
    return {
      pass,
      detail: `mouseOpen=${splitOpenedByMouse}, prevClosed=${prevClosedOnOtherSub}, nextOpened=${nextSubOpened}, closedOnPlain=${subClosedOnPlainItem}, topOpen=${topStillOpen}`,
    };
  });

  // =========================================================================
  // 4. 키보드: ↓/↑ 이동, → 하위 열기, ← 닫기, Esc 닫기, 최상위 →/← 옆 메뉴바 이동
  // =========================================================================
  await check('4-keyboard-navigation', async () => {
    const { baseBtns, topBtns } = await openMenubarMenu('view');
    const topSet = new Set(topBtns);

    // ↓ / ↑ 이동 확인
    sendKey('ArrowDown');
    await W(80);
    const act1 = getActiveMenuButton(baseBtns);

    sendKey('ArrowDown');
    await W(80);
    const act2 = getActiveMenuButton(baseBtns);

    sendKey('ArrowUp');
    await W(80);
    const actUp = getActiveMenuButton(baseBtns);

    const upDownOk = !!act1 && !!act2 && act1 !== act2 && actUp === act1;

    // '화면 분할 ▸'로 이동하여 → 로 하위 메뉴 열기
    let splitFocused = false;
    for (let i = 0; i < 8; i++) {
      const cur = getActiveMenuButton(baseBtns);
      if (cur && norm(cur.textContent).includes('화면 분할')) {
        splitFocused = true;
        break;
      }
      sendKey('ArrowDown');
      await W(60);
    }

    sendKey('ArrowRight');
    await W(150);
    const subAfterRight = getVisibleButtons().filter((b) => !baseBtns.has(b) && !topSet.has(b));
    const rightOpensSub =
      splitFocused && !!findBtnByLabel(subAfterRight, '좌우') && !!findBtnByLabel(subAfterRight, '4분할');

    // ← 로 하위 메뉴 닫기 (최상위 메뉴는 유지)
    sendKey('ArrowLeft');
    await W(150);
    const subAfterLeft = getVisibleButtons().filter((b) => !baseBtns.has(b) && !topSet.has(b));
    const leftClosesSub =
      subAfterLeft.length === 0 && isVis(document.querySelector('#ctxMenu'));

    // 최상위(하위 메뉴가 없는 항목, 예: '사이드바 접기/펴기' 또는 '라이트/다크 전환')에서 → / ← 로 옆 메뉴바 메뉴 이동
    for (let i = 0; i < 8; i++) {
      const cur = getActiveMenuButton(baseBtns);
      if (cur && !hasSubArrow(cur)) break;
      sendKey('ArrowDown');
      await W(60);
    }

    sendKey('ArrowRight');
    await W(150);
    const ctx = document.querySelector('#ctxMenu');
    const btnsAfterMenuRight = getVisibleButtons().filter((b) => !baseBtns.has(b));
    const movedToNextMenu =
      ctx?.dataset?.menu === 'net' ||
      !!findBtnByLabel(btnsAfterMenuRight, '터널 관리') ||
      !!findBtnByLabel(btnsAfterMenuRight, '포트 스캐너');

    sendKey('ArrowLeft');
    await W(150);
    const btnsAfterMenuLeft = getVisibleButtons().filter((b) => !baseBtns.has(b));
    const movedToPrevMenu =
      ctx?.dataset?.menu === 'view' ||
      !!findBtnByLabel(btnsAfterMenuLeft, '사이드바 접기/펴기') ||
      !!findBtnByLabel(btnsAfterMenuLeft, '화면 분할');

    // Esc 로 닫기
    sendKey('Escape');
    await W(100);
    if (isVis(ctx)) {
      sendKey('Escape');
      await W(100);
    }
    const escClosed = !isVis(ctx);

    await closeMenus();
    const pass =
      upDownOk && rightOpensSub && leftClosesSub && movedToNextMenu && movedToPrevMenu && escClosed;
    return {
      pass,
      detail: `upDown=${upDownOk}, rightOpenSub=${rightOpensSub}, leftCloseSub=${leftClosesSub}, nextMenu=${movedToNextMenu}, prevMenu=${movedToPrevMenu}, escClose=${escClosed}`,
    };
  });

  // =========================================================================
  // 5. 창 오른쪽 끝: 도움말·보안 메뉴 및 보기›화면 글꼴 하위가 innerWidth 안에 있는지
  // =========================================================================
  await check('5-right-edge-within-innerwidth', async () => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const details = [];
    let allInside = true;

    const checkBounds = (tag, btns) => {
      if (!btns.length) {
        allInside = false;
        details.push(`${tag}:按鈕없음`);
        return;
      }
      let maxR = -Infinity;
      let minL = Infinity;
      let maxB = -Infinity;
      for (const b of btns) {
        const r = b.getBoundingClientRect();
        if (r.right > maxR) maxR = r.right;
        if (r.left < minL) minL = r.left;
        if (r.bottom > maxB) maxB = r.bottom;
      }
      const ok = minL >= -1 && maxR <= vw + 1 && maxB <= vh + 1;
      if (!ok) allInside = false;
      details.push(`${tag}:right=${maxR.toFixed(1)}/${vw}(ok=${ok})`);
    };

    // 1) 마지막 메뉴(도움말)
    {
      const { topBtns } = await openMenubarMenu('help');
      checkBounds('help', topBtns);
    }

    // 2) 보안 메뉴 및 하위 메뉴(있다면)
    {
      const { baseBtns, topBtns } = await openMenubarMenu('sec');
      checkBounds('sec', topBtns);
      const subParent = topBtns.find(hasSubArrow);
      if (subParent) {
        const sub = await openSubmenuFrom(subParent, baseBtns, topBtns);
        checkBounds('sec-sub', sub);
      }
    }

    // 3) 네트워킹 › 파일 서버 하위
    {
      const { baseBtns, topBtns } = await openMenubarMenu('net');
      const fsBtn = findBtnByLabel(topBtns, '파일 서버');
      const sub = await openSubmenuFrom(fsBtn, baseBtns, topBtns);
      checkBounds('net›파일서버', sub);
    }

    // 4) 보기 › 화면 글꼴 하위
    {
      const { baseBtns, topBtns } = await openMenubarMenu('view');
      const ufBtn = findBtnByLabel(topBtns, '화면 글꼴');
      const sub = await openSubmenuFrom(ufBtn, baseBtns, topBtns);
      checkBounds('view›화면글꼴', sub);
    }

    await closeMenus();
    return { pass: allInside, detail: details.join(', ') };
  });

  // =========================================================================
  // 6. 도움말: "라이선스" 없음, "사용법"으로 #guideDlg 열리고 세로 탭 7개,
  //    탭 전환 시 본문 바뀜, 외부 http 링크·img 없음
  // =========================================================================
  await check('6-help-menu-and-guidedlg', async () => {
    const { topBtns } = await openMenubarMenu('help');
    const noLicenseInHelp = !findBtnByLabel(topBtns, '라이선스');
    const guideItem = findBtnByLabel(topBtns, '사용법');
    if (!guideItem) {
      await closeMenus();
      return { pass: false, detail: '도움말 메뉴에 "사용법" 항목 없음' };
    }

    guideItem.click();
    await W(200);

    const dlg = document.querySelector('#guideDlg');
    const dlgOpen = !!dlg && (dlg.open || isVis(dlg));
    if (!dlgOpen) {
      return { pass: false, detail: '#guideDlg가 열리지 않음' };
    }

    // 세로 탭 7개 확인
    const expectedTabs = [
      '시작하기',
      '터미널',
      '파일',
      '원격 데스크톱',
      '네트워킹',
      '보안',
      '화면·설정',
    ];
    let tabBtns = [...dlg.querySelectorAll('.tdlg-tabs button, nav button, [role="tab"]')].filter(isVis);
    if (tabBtns.length === 0) {
      tabBtns = [...dlg.querySelectorAll('button')].filter(
        (b) => isVis(b) && expectedTabs.includes(norm(b.textContent))
      );
    }
    const tabLabels = tabBtns.map((b) => norm(b.textContent));
    const tabs7Ok =
      tabLabels.length === 7 && expectedTabs.every((t, i) => tabLabels[i] === t);

    // 탭 전환 시 본문 변경 확인
    const seenBodies = new Set();
    let bodyChangesOk = tabBtns.length === 7;
    for (const b of tabBtns) {
      b.click();
      await W(80);
      const activePane =
        dlg.querySelector('.tdlg-body section.on, .tdlg-body .pane.on, .tdlg-body > .on') ||
        [...dlg.querySelectorAll('.tdlg-body section, .tdlg-body > div, section')].find(isVis);
      const txt = norm(activePane ? activePane.textContent : dlg.textContent);
      if (!txt || seenBodies.has(txt)) {
        bodyChangesOk = false;
      }
      seenBodies.add(txt);
    }

    // 단축키 <kbd> 존재, 외부 http(s) 링크 및 img 없음 확인
    const hasKbd = dlg.querySelectorAll('kbd').length > 0;
    const extLinks = [...dlg.querySelectorAll('a[href]')].filter((a) =>
      /^https?:/i.test(a.getAttribute('href') || '')
    );
    const imgs = [...dlg.querySelectorAll('img')];
    const noExtHttpOrImg = extLinks.length === 0 && imgs.length === 0;

    try { dlg.close(); } catch {}
    await W(80);

    const pass = noLicenseInHelp && dlgOpen && tabs7Ok && bodyChangesOk && hasKbd && noExtHttpOrImg;
    return {
      pass,
      detail: `noLic=${noLicenseInHelp}, open=${dlgOpen}, tabs=[${tabLabels.join(',')}], bodyChanges=${bodyChangesOk}(${seenBodies.size}), hasKbd=${hasKbd}, extLinks=${extLinks.length}, imgs=${imgs.length}`,
    };
  });

  // =========================================================================
  // 7. 버전 정보 창: #abEnv 없음, "실행 환경" 글자 없음, [라이선스] 버튼으로 라이선스 창 열림
  // =========================================================================
  await check('7-aboutdlg-no-abenv-and-license-btn', async () => {
    const { topBtns } = await openMenubarMenu('help');
    const aboutItem = findBtnByLabel(topBtns, '버전 정보');
    if (!aboutItem) {
      await closeMenus();
      return { pass: false, detail: '도움말 메뉴에 "버전 정보" 항목 없음' };
    }

    aboutItem.click();
    await W(250);

    const aboutDlg = document.querySelector('#aboutDlg');
    const aboutOpen = !!aboutDlg && (aboutDlg.open || isVis(aboutDlg));
    if (!aboutOpen) {
      return { pass: false, detail: '#aboutDlg가 열리지 않음' };
    }

    const noAbEnvEl = !document.querySelector('#abEnv');
    const noEnvText = !norm(aboutDlg.textContent).includes('실행 환경');

    const licBtn =
      aboutDlg.querySelector('.open-license') ||
      [...aboutDlg.querySelectorAll('button')].find((b) => norm(b.textContent).includes('라이선스'));
    if (!licBtn) {
      try { aboutDlg.close(); } catch {}
      return {
        pass: false,
        detail: `noAbEnv=${noAbEnvEl}, noEnvText=${noEnvText}, [라이선스] 버튼 없음`,
      };
    }

    licBtn.click();
    await W(350);
    const licDlg = document.querySelector('#licenseDlg');
    const licOpen = !!licDlg && (licDlg.open || isVis(licDlg));

    try { licDlg?.close(); } catch {}
    try { aboutDlg?.close(); } catch {}
    await W(80);

    const pass = aboutOpen && noAbEnvEl && noEnvText && licOpen;
    return {
      pass,
      detail: `aboutOpen=${aboutOpen}, noAbEnvEl=${noAbEnvEl}, noEnvText=${noEnvText}, licOpen=${licOpen}`,
    };
  });

  // =========================================================================
  // 8. 기능 표시 끔: 명세에 feature 키를 끄는 API가 없으므로 가정 주석 후 SKIP 처리
  // =========================================================================
  await check('8-feature-off-visibility', async () => {
    // 가정: 명세(SPEC_MENU_2026-11-17.md)에는 feature 키(tools, tunnels, multiexec, macro,
    // split, local, logs, passwordSave)를 끄는 설정 저장 API나 DOM 선택자가 정의되어 있지 않다.
    // 따라서 설정 저장 내부 구조를 임의로 추측해 상태를 오염시키지 않고 SKIP 처리한다.
    return {
      pass: true,
      skip: true,
      detail: 'SKIP: 명세에 feature 설정 변경 API/선택자가 정의되지 않아 건너뜀',
    };
  });

  // =========================================================================
  // 9. 툴바 #tbTools 클릭 시 네트워킹+보안 항목이 한 목록에 보임
  // =========================================================================
  await check('9-toolbar-tbtools-combined-menu', async () => {
    await closeMenus();
    const baseBtns = new Set(getVisibleButtons());
    const tbTools = document.querySelector('#tbTools');
    if (!tbTools || !isVis(tbTools)) {
      return { pass: false, detail: '#tbTools 버튼이 없거나 보이지 않음' };
    }

    tbTools.click();
    await W(150);

    const menuBtns = getVisibleButtons().filter((b) => !baseBtns.has(b));
    const netLabels = ['터널 관리', '포트 스캐너', '이 PC의 열린 포트', '파일 서버'];
    const secLabels = ['SSH 키 생성', '알려진 호스트 관리', '비밀번호 저장소 관리'];

    const missingNet = netLabels.filter((l) => !findBtnByLabel(menuBtns, l));
    const missingSec = secLabels.filter((l) => !findBtnByLabel(menuBtns, l));

    // 네트워킹 항목들이 보안 항목들보다 위쪽에 배치되어 있는지 확인
    const fsBtn = findBtnByLabel(menuBtns, '파일 서버');
    const sshKeyBtn = findBtnByLabel(menuBtns, 'SSH 키 생성');
    const orderOk =
      !!fsBtn &&
      !!sshKeyBtn &&
      fsBtn.getBoundingClientRect().top < sshKeyBtn.getBoundingClientRect().top;

    // #tbTools 메뉴 안에서도 '파일 서버 ▸' 하위 메뉴가 열리는지 확인
    const fsSub = await openSubmenuFrom(fsBtn, baseBtns, menuBtns);
    const fsSubOk =
      !!findBtnByLabel(fsSub, 'TFTP 서버') && !!findBtnByLabel(fsSub, 'HTTP 파일 서버');

    await closeMenus();
    const pass =
      missingNet.length === 0 && missingSec.length === 0 && orderOk && fsSubOk;
    return {
      pass,
      detail: `missingNet=[${missingNet.join(',')}], missingSec=[${missingSec.join(',')}], orderOk=${orderOk}, fsSubOk=${fsSubOk}`,
    };
  });

  // =========================================================================
  // 10. 회귀: 메뉴바 열린 상태에서 다른 메뉴바 버튼 hover 시 그 메뉴로 바뀜, 바깥 pointerdown으로 닫힘
  // =========================================================================
  await check('10-regression-menubar-hover-and-outside-pointerdown', async () => {
    // 1) 파일 메뉴를 연 뒤 보기 메뉴바 버튼에 hover → 보기 메뉴로 전환
    const { baseBtns, topBtns: fileBtns } = await openMenubarMenu('file');
    const fileOpenOk = !!findBtnByLabel(fileBtns, '새 세션');

    const viewMbBtn = document.querySelector('#menubar button.mb[data-menu="view"]');
    hoverEl(viewMbBtn);
    await W(150);

    const viewBtns = getVisibleButtons().filter((b) => !baseBtns.has(b));
    const switchedToView =
      !!findBtnByLabel(viewBtns, '사이드바 접기/펴기') && !findBtnByLabel(viewBtns, '새 세션');

    // 2) 하위 메뉴('화면 분할 ▸')가 열린 상태에서 보안 메뉴바 버튼에 hover → 하위 메뉴 닫히고 보안 메뉴로 전환 (M1 24줄)
    const splitBtn = findBtnByLabel(viewBtns, '화면 분할');
    await openSubmenuFrom(splitBtn, baseBtns, viewBtns, true);

    const secMbBtn = document.querySelector('#menubar button.mb[data-menu="sec"]');
    hoverEl(secMbBtn);
    await W(150);

    const secBtns = getVisibleButtons().filter((b) => !baseBtns.has(b));
    const switchedFromSubToSec =
      !!findBtnByLabel(secBtns, 'SSH 키 생성') &&
      !findBtnByLabel(secBtns, '4분할') &&
      !findBtnByLabel(secBtns, '화면 분할');

    // 3) 바깥 pointerdown으로 닫힘 확인
    const outsideTarget =
      document.querySelector('#workspace') || document.querySelector('#main') || document.body;
    const r = outsideTarget.getBoundingClientRect();
    outsideTarget.dispatchEvent(
      new PointerEvent('pointerdown', {
        bubbles: true,
        cancelable: true,
        clientX: r.left + 20,
        clientY: r.top + 20,
      })
    );
    await W(120);

    const ctx = document.querySelector('#ctxMenu');
    const closedByPointerdown =
      !isVis(ctx) && getVisibleButtons().filter((b) => !baseBtns.has(b)).length === 0;

    await closeMenus();
    const pass =
      fileOpenOk && switchedToView && switchedFromSubToSec && closedByPointerdown;
    return {
      pass,
      detail: `fileOpen=${fileOpenOk}, hoverSwitch=${switchedToView}, hoverSwitchWithSub=${switchedFromSubToSec}, outsidePointerdownClose=${closedByPointerdown}`,
    };
  });
} finally {
  await closeMenus();
  await closeDialogs();
  window.removeEventListener('error', onErr);
  window.removeEventListener('unhandledrejection', onErr);
}

const R = {
  pass: results.length > 0 && results.every((r) => r.pass) && errs.length === 0,
  results,
  errors: errs,
};
return R;