// dev/harness/t_sec_h1.js: S1 UI 모니터링 값 XSS 방지 및 Load 표시 시험
const origMonitor = typeof SETTINGS !== "undefined" ? SETTINGS.monitor : undefined;
let s = null;
const checks = [];

try {
    // 1. 모니터링 설정 활성화 (기존 설정 백업)
    if (typeof SETTINGS !== "undefined" && !SETTINGS.monitor) {
        SETTINGS.monitor = true;
    }

    // 2. 가짜 세션/탭 열기
    s = await openFake();
    if (!s) {
        return { pass: false, error: "openFake() returned falsy session" };
    }

    // 3. XSS 페이로드 주입 및 renderStatus() 호출
    delete window.__xss;
    s.mon = {
        cpu: 5,
        mem: [1, 2],
        disk: [1, 2],
        net: [0, 0],
        load: ['<img src=x onerror="window.__xss=1">', "0", "0"],
        uptime: 10,
    };

    if (typeof renderStatus === "function") {
        renderStatus();
    }

    // onerror 이벤트 핸들러가 비동기로 실행될 수 있도록 대기
    await new Promise((resolve) => setTimeout(resolve, 50));

    const sbText = document.querySelector("#sbText");
    const hasImgElement = sbText ? sbText.querySelector("img") !== null : false;
    const xssExecuted = window.__xss !== undefined;

    checks.push({
        name: "S1-1 #sbText 내부에 img 태그가 DOM 요소로 생성되지 않음",
        ok: !hasImgElement,
        detail: `hasImgElement=${hasImgElement}`,
    });

    checks.push({
        name: "S1-2 window.__xss 가 실행되지 않음 (undefined 유지)",
        ok: !xssExecuted,
        detail: `window.__xss=${window.__xss}`,
    });

    // 4. load가 null일 때 'Load' 텍스트 생략 확인
    s.mon.load = null;
    if (typeof renderStatus === "function") {
        renderStatus();
    }
    await new Promise((resolve) => setTimeout(resolve, 20));

    const sbTextContent = sbText ? (sbText.textContent || "") : "";
    const hasLoadText = /load/i.test(sbTextContent);

    checks.push({
        name: "S1-3 s.mon.load === null 일 때 'Load' 텍스트가 표시되지 않음",
        ok: !hasLoadText,
        detail: `textContent=${sbTextContent}`,
    });

    const pass = checks.every((c) => c.ok);
    return {
        pass,
        checks,
        summary: `${checks.filter((c) => c.ok).length}/${checks.length} 통과`,
    };
} catch (err) {
    return {
        pass: false,
        error: String(err && err.stack ? err.stack : err),
        checks,
    };
} finally {
    // 모니터링 설정 원복
    if (typeof SETTINGS !== "undefined" && origMonitor !== undefined) {
        SETTINGS.monitor = origMonitor;
    }

    // 시험 후 탭 닫기
    if (s) {
        try {
            if (typeof closeTab === "function") {
                await closeTab(s.id ?? s);
            } else if (typeof closeSession === "function") {
                await closeSession(s.id ?? s);
            } else if (typeof s.close === "function") {
                await s.close();
            }
        } catch (_) {}
    }
}
