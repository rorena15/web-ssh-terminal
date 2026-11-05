'use strict';
/* 키워드 하이라이트
 * 출력 스트림을 바꾸지 않고 xterm 데코레이션으로 글자색만 덧칠한다 → 로그·복사 내용은 원본 그대로.
 * 전체화면 프로그램(vim, top 등 alternate buffer)에서는 동작하지 않음. */

let HL_RULES = [];
function compileHighlight(rules) {
  HL_RULES = [];
  for (const r of rules || []) {
    if (!r.on || !r.pattern) continue;
    try { HL_RULES.push({ re: new RegExp(r.pattern, 'gi'), color: typeof adaptHighlight === 'function' ? adaptHighlight(r.color) : r.color }); } catch { /* 잘못된 정규식은 무시 */ }
  }
}

class Highlighter {
  constructor(term) {
    this.term = term;
    this.mark = null;          // 마지막으로 칠한 줄 위치 (스크롤백이 잘려도 따라 움직이는 마커)
    this.groups = [];          // 줄마다 {marker, decos}, 줄 순서대로
    this.raf = 0;
    this.cell = null;
    term.onWriteParsed(() => this.schedule());
  }

  // 규칙·색이 바뀌면 기존 색칠을 지우고 최근 2000줄을 다시 칠함
  reset() {
    this.groups.forEach(dropGroup);
    this.groups = [];
    this.mark?.dispose();
    this.mark = null;
    this.full = true;
    this.scan();
  }

  schedule() {
    if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = 0; this.scan(); });
  }

  scan() {
    const t = this.term, b = t.buffer.active;
    if (b.type !== 'normal' || !HL_RULES.length) return;
    const cur = b.baseY + b.cursorY;
    // 커서는 화면 안에서 위로 올라가 줄을 고쳐 쓸 수 있다(진행 표시 등) → 화면 맨 윗줄부터는 매번 다시 칠함
    let from = this.mark && !this.mark.isDisposed && this.mark.line >= 0
      ? Math.min(this.mark.line, b.baseY) : Math.max(0, cur - (this.full ? 2000 : t.rows));
    this.full = false;
    if (from > cur) from = cur;
    if (cur - from > 2000) from = cur - 2000;           // 대량 출력 시 마지막 2000줄만
    const g = this.groups;
    while (g.length && (g[g.length - 1].marker.isDisposed || g[g.length - 1].marker.line >= from)) dropGroup(g.pop());
    if (g.length > 4000) this.groups = g.filter((x) => !x.marker.isDisposed);   // 스크롤백에서 잘려 나간 줄 정리
    for (let y = from; y <= cur; y++) {
      const grp = this.line(y, cur);
      if (grp) this.groups.push(grp);
    }
    this.mark?.dispose();
    this.mark = t.registerMarker(0);
  }

  line(y, cur) {
    const line = this.term.buffer.active.getLine(y);
    if (!line) return null;
    // 셀 단위로 문자열을 만들면서 문자 위치 → 열 위치 대응표 작성 (한글 등 2칸 문자 대응)
    let str = '';
    const col = [], wid = [];
    for (let x = 0; x < line.length; x++) {
      const c = line.getCell(x, this.cell);
      this.cell = c;
      const w = c.getWidth();
      if (w === 0) continue;
      const ch = c.getChars() || ' ';
      for (let i = 0; i < ch.length; i++) { col.push(x); wid.push(w); }
      str += ch;
    }
    const s = str.trimEnd();
    if (!s) return null;
    const out = [];
    let marker = null;
    const taken = new Uint8Array(s.length);
    for (const r of HL_RULES) {
      r.re.lastIndex = 0;
      let m;
      while ((m = r.re.exec(s))) {
        if (!m[0]) { r.re.lastIndex++; continue; }
        const a = m.index, z = a + m[0].length - 1;
        if (taken.subarray(a, z + 1).some((v) => v)) continue;   // 앞 규칙이 이미 칠한 곳은 건너뜀
        taken.fill(1, a, z + 1);
        marker ||= this.term.registerMarker(y - cur);
        if (!marker) return out.length ? { marker, decos: out } : null;
        const d = this.term.registerDecoration({
          marker, x: col[a], width: col[z] + wid[z] - col[a], foregroundColor: r.color, layer: 'top',
        });
        if (d) {
          out.push(d);
          marker.onDispose(() => d.dispose());
        }
      }
    }
    if (marker && !out.length) { marker.dispose(); return null; }
    return marker ? { marker, decos: out } : null;
  }
}

function dropGroup(g) {
  g.decos.forEach((d) => d.dispose());
  g.marker.dispose();
}
