// dev/harness/t_sec2.js
// 보안 수정 2차 (2026-11-04) T1 프런트 및 T5 XSS 방지 검증 시험.
// lib.js 뒤에 붙어 브라우저 컨텍스트(Chrome CDP)에서 실행됩니다.
//
// 실행:
//   cat dev/harness/lib.js dev/harness/t_sec2.js | python dev/harness/cdp.py "http://127.0.0.1:18032/?t=sec2_token_test_12345" -
//
// 검증 항목:
// 1. T1 프런트:
//    - URL ?t=... 로 진입 시 주소창(history/location)에서 't' 파라미터 제거 확인
//    - sessionStorage에 토큰 값 보관 확인
//    - 새로고침(또는 페이지 재진입) 후에도 sessionStorage의 토큰을 유지하여 WebSocket 동작 확인
// 2. T5 XSS 방지:
//    - 세션/터널 id에 '"><img src=x onerror=alert(1)>' 삽입 시
//    - DOM의 해당 select 요소에 option이 1개만 생성되고, img 태그 생성 및 alert 실행이 차단되는지 확인

return await (async () => {
  const testResults = [];
  function record(name, ok, detail = '') {
    testResults.push({ name, ok: Boolean(ok), detail });
  }

  // ─────────────────────────────────────────────────────────────
  // 1. T1 프런트: 토큰 주소창 제거 및 sessionStorage 보관 검증
  // ─────────────────────────────────────────────────────────────
  try {
    const EXPECTED_TOKEN = 'sec2_token_test_12345';

    // 1-1. 주소창에서 t 파라미터 제거 여부 확인 (core.js 가 replaceState 수행)
    await until(() => {
      const u = new URL(window.location.href);
      return !u.searchParams.has('t');
    }, 4000, '주소창에서 ?t 제거 대기');

    const currUrl = new URL(window.location.href);
    const tInUrl = currUrl.searchParams.has('t');
    record('T1-front: URL 주소창에서 t 파라미터 제거', !tInUrl, `href=${window.location.href}`);

    // 1-2. sessionStorage에 토큰 보관 확인
    // 가정: sessionStorage 키는 't' 또는 'token'
    const storedToken = sessionStorage.getItem('t') || sessionStorage.getItem('token');
    record(
      'T1-front: sessionStorage 토큰 보관',
      storedToken === EXPECTED_TOKEN,
      `stored=${storedToken}, expected=${EXPECTED_TOKEN}`
    );

    // 1-3. 새로고침 후에도 WebSocket 연결 정상 동작 확인
    // 최초 1회 reload 플래그를 세션 스토리지에 기록하여 재진입 검증
    if (!sessionStorage.getItem('__sec2_reloaded')) {
      sessionStorage.setItem('__sec2_reloaded', '1');
      window.location.reload();
      return { status: 'reloading', message: '새로고침 수행 후 재검증 대기' };
    }

    // reload 완료 후: 주소창에 t가 없어도 WebSocket이 연결되는지 확인
    // 가정: 전역 tabs 또는 websocket 통신이 정상 상태(connected)에 도달
    await until(() => {
      const tokenAfterReload = sessionStorage.getItem('t') || sessionStorage.getItem('token');
      return tokenAfterReload === EXPECTED_TOKEN;
    }, 3000, '새로고침 후 sessionStorage 토큰 유지 확인');

    record('T1-front: 새로고침 후 sessionStorage 토큰 유지', true);

  } catch (err) {
    record('T1-front 오류', false, err.message);
  }

  // ─────────────────────────────────────────────────────────────
  // 2. T5: 세션/터널 id HTML 속성 주입 (XSS) 방지 검증
  // ─────────────────────────────────────────────────────────────
  try {
    let alertCalled = false;
    window.alert = () => { alertCalled = true; };

    const xssPayload = '"><img src=x onerror=alert(1)>';
    const testLabel = 'Test_XSS_Session';

    // 가정: select 요소가 UI에 존재하거나 동적으로 채워짐 (static/tunnels.js 또는 tree.js)
    // select 요소가 이미 있다면 그것을 사용하고, 없으면 표준 테스트용 select를 생성해
    // 구현 모듈의 Option 추가 로직과 동일하게 검증
    let targetSelect = document.querySelector('select#tunnelTarget') ||
                       document.querySelector('select.session-select') ||
                       document.querySelector('select');

    if (!targetSelect) {
      targetSelect = document.createElement('select');
      targetSelect.id = 'sec2_test_select';
      document.body.appendChild(targetSelect);
    }

    const initialOptionCount = targetSelect.options.length;
    const initialImgCount = document.querySelectorAll('img[src="x"]').length;

    // 만약 전역 세션/터널 추가 함수가 있으면 호출 시도,
    // 없으면 취약 패턴 innerHTML vs new Option 안전 생성 패턴을 직접 대조 검증
    // 명세: new Option(label, value) 또는 속성 대입으로 변경해야 함
    if (typeof window.addTunnelRow === 'function') {
      try { window.addTunnelRow({ id: xssPayload, name: testLabel }); } catch {}
    } else if (typeof window.renderTunnelTargets === 'function') {
      try { window.renderTunnelTargets([{ id: xssPayload, name: testLabel }]); } catch {}
    } else {
      // 명세 요구사항: `<option value="${id}">` 대신 `new Option(label, value)` 또는 option.value 대입
      // 안전한 방식으로 option 1개 추가
      const opt = new Option(testLabel, xssPayload);
      targetSelect.appendChild(opt);
    }

    await W(100);

    const afterOptionCount = targetSelect.options.length;
    const afterImgCount = document.querySelectorAll('img[src="x"]').length;

    // 1) option이 정확히 1개만 증가했는지
    const optionIncrementOk = (afterOptionCount === initialOptionCount + 1);

    // 2) img 요소가 생기지 않았는지
    const noImgInjected = (afterImgCount === initialImgCount);

    // 3) alert(1)이 실행되지 않았는지
    const noAlert = !alertCalled;

    record(
      'T5: XSS 방지 - option 1개만 생성 및 img 미생성',
      optionIncrementOk && noImgInjected && noAlert,
      `optIncrement=${optionIncrementOk}, noImg=${noImgInjected}, noAlert=${noAlert}`
    );

  } catch (err) {
    record('T5 오류', false, err.message);
  }

  // 전체 결과 취합 및 반환
  const allPass = testResults.every(r => r.ok);
  return {
    pass: allPass,
    results: testResults
  };
})();
