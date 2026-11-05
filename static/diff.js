'use strict';
/* 텍스트 비교: 줄 단위 Myers diff → 좌우 비교 화면.
 * 쓰는 곳: SFTP 두 파일 비교 · 로컬 파일과 비교 · 다른 탭의 같은 경로와 비교 · 편집기 "변경 내용". */

// Myers O(ND) — 같음(=) / 지움(-) / 넣음(+) 목록
function diffLines(a, b) {
  const n = a.length, m = b.length, max = n + m;
  if (n * m > 4e7 && max > 40000) return [...a.map((x) => ['-', x]), ...b.map((x) => ['+', x])];   // 너무 크면 통째로
  const v = new Int32Array(2 * max + 2), trace = [];
  let found = false;
  for (let d = 0; d <= max && !found; d++) {
    // 기록이 커지면(약 200MB) 줄 단위 비교를 포기하고 통째로 표시 — 일치 줄이 거의 없는 큰 파일에서 브라우저가 멈추지 않게
    if (d * v.length > 5e7) return [...a.map((x) => ['-', x]), ...b.map((x) => ['+', x])];
    trace.push(v.slice());
    for (let k = -d; k <= d; k += 2) {
      let x = k === -d || (k !== d && v[max + k - 1] < v[max + k + 1]) ? v[max + k + 1] : v[max + k - 1] + 1;
      let y = x - k;
      while (x < n && y < m && a[x] === b[y]) { x++; y++; }
      v[max + k] = x;
      if (x >= n && y >= m) { found = true; break; }
    }
  }
  const out = [];
  let x = n, y = m;
  for (let d = trace.length - 1; d >= 0; d--) {
    const vv = trace[d], k = x - y;
    const pk = k === -d || (k !== d && vv[max + k - 1] < vv[max + k + 1]) ? k + 1 : k - 1;
    const px = vv[max + pk], py = px - pk;
    while (x > px && y > py) { out.push(['=', a[x - 1]]); x--; y--; }
    if (d > 0) { if (x === px) out.push(['+', b[y - 1]]); else out.push(['-', a[x - 1]]); }
    x = px; y = py;
  }
  return out.reverse();
}

// 좌우 비교 표: 바뀐 줄끼리 짝지어 한 행에
function showDiff(titleA, textA, titleB, textB) {
  const a = textA.replace(/\r\n/g, '\n').split('\n'), b = textB.replace(/\r\n/g, '\n').split('\n');
  const ops = diffLines(a, b);
  const rows = [];
  let la = 0, lb = 0, i = 0;
  while (i < ops.length) {
    if (ops[i][0] === '=') { la++; lb++; rows.push(['eq', la, ops[i][1], lb, ops[i][1]]); i++; continue; }
    const del = [], add = [];
    while (i < ops.length && ops[i][0] !== '=') { (ops[i][0] === '-' ? del : add).push(ops[i][1]); i++; }
    for (let k = 0; k < Math.max(del.length, add.length); k++) {
      const L = k < del.length, Rr = k < add.length;
      rows.push([L && Rr ? 'chg' : L ? 'del' : 'add', L ? ++la : '', L ? del[k] : '', Rr ? ++lb : '', Rr ? add[k] : '']);
    }
  }
  const changed = rows.filter((r) => r[0] !== 'eq').length;
  const b2 = toolWindow('비교', `
    <div class="row"><span class="grow hint">${changed ? `다른 줄 ${changed}개` : '두 내용이 같습니다'}</span>
      <label class="check"><input type="checkbox" class="df-only" ${changed ? 'checked' : ''}> 다른 부분만 (앞뒤 3줄)</label>
      <button class="df-next">다음 차이 ↓</button></div>
    <div class="diff"><table><colgroup><col class="ln"><col><col class="ln"><col></colgroup>
      <tr><th></th><th class="mono">${escapeHtml(titleA)}</th><th></th><th class="mono">${escapeHtml(titleB)}</th></tr><tbody></tbody></table></div>`, true);
  const tb = $('tbody', b2);
  const render = () => {
    const only = $('.df-only', b2).checked;
    const keep = new Set();
    if (only) rows.forEach((r, j) => { if (r[0] !== 'eq') for (let q = j - 3; q <= j + 3; q++) keep.add(q); });
    let html = '', gap = false;
    rows.forEach((r, j) => {
      if (only && !keep.has(j)) { if (!gap) { html += '<tr class="gap"><td colspan="4">⋯</td></tr>'; gap = true; } return; }
      gap = false;
      html += `<tr class="${r[0]}"><td class="ln">${r[1]}</td><td class="mono">${escapeHtml(r[2])}</td><td class="ln">${r[3]}</td><td class="mono">${escapeHtml(r[4])}</td></tr>`;
    });
    tb.innerHTML = html;
  };
  $('.df-only', b2).onchange = render;
  let at = -1;
  $('.df-next', b2).onclick = () => {
    const ch = $$('tr.chg,tr.del,tr.add', tb);
    if (!ch.length) return;
    at = (at + 1) % ch.length;
    ch[at].scrollIntoView({ block: 'center' });
    ch.forEach((t) => t.classList.remove('cur'));
    ch[at].classList.add('cur');
  };
  render();
}

// SFTP 패널에서 쓰는 비교 동작
async function diffTwoRemote(panel, x, y) {
  try {
    const [ra, rb] = [await panel.call('read', { path: joinPath(panel.cwd, x.name) }), await panel.call('read', { path: joinPath(panel.cwd, y.name) })];
    showDiff(x.name, ra.text, y.name, rb.text);
  } catch (e) { toast(e.message, 3000); }
}
function diffWithLocal(panel, x) {
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.onchange = async () => {
    const f = inp.files[0];
    if (!f) return;
    try {
      const r = await panel.call('read', { path: joinPath(panel.cwd, x.name) });
      const buf = await f.arrayBuffer();
      let t;
      try { t = new TextDecoder('utf-8', { fatal: true }).decode(buf); } catch { t = new TextDecoder('euc-kr').decode(buf); }
      showDiff(`${tabLabel(panel.s)}:${x.name}`, r.text, `내 PC: ${f.name}`, t);
    } catch (e) { toast(e.message, 3000); }
  };
  inp.click();
}
// 다른 연결된 탭(서버)의 같은 경로 파일과 비교 — 서버 간 설정 차이 확인
function diffWithOtherTab(panel, x, ev) {
  const others = tabs.filter((t) => t.sftp && t !== panel.s && t.state === 'on');
  if (!others.length) return toast('비교할 다른 연결된 탭이 없습니다');
  const path = joinPath(panel.cwd, x.name);
  showMenu(ev?.clientX ?? 200, ev?.clientY ?? 200, others.map((t) => ({
    label: `${tabLabel(t)} : ${path}`,
    action: async () => {
      try {
        const [ra, rb] = [await panel.call('read', { path }), await t.sftp.call('read', { path })];
        showDiff(`${tabLabel(panel.s)}:${path}`, ra.text, `${tabLabel(t)}:${path}`, rb.text);
      } catch (e) { toast(e.message, 3000); }
    },
  })));
}
