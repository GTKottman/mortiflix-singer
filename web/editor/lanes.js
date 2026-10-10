// Parameter lanes under the roll: paint a curve with the mouse, right-drag to erase it. Shares the roll's timeline.
import { LANES } from './model.js';

const KEYW = 52;
export class Lanes {
  constructor(canvas, app, roll) {
    this.cv = canvas; this.app = app; this.roll = roll; this.lane = 'energy'; this.drag = null;
    canvas.addEventListener('mousedown', (e) => { e.preventDefault(); this.drag = { erase: e.button === 2, pts: [] }; this.paint(e); });
    addEventListener('mousemove', (e) => this.drag && this.paint(e));
    addEventListener('mouseup', () => this.commit());
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    new ResizeObserver(() => this.draw()).observe(canvas);
  }
  spec() { return LANES[this.lane]; }
  V(y) { const s = this.spec(), H = this.cv.clientHeight; return s.max - (y / H) * (s.max - s.min); }
  Yv(v) { const s = this.spec(), H = this.cv.clientHeight; return (s.max - v) / (s.max - s.min) * H; }
  paint(e) {
    const r = this.cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (x < KEYW) return;
    const tick = Math.round(this.roll.T(x)), s = this.spec();
    this.drag.pts.push([tick, Math.round(Math.max(s.min, Math.min(s.max, this.V(y))) * 100) / 100]);
    this.draw();
  }
  // smooth the lane's curve (over the selected notes' span, or all of it): a moving average over ~1/8 note
  smooth() {
    const lane = this.lane, t = this.app.track(), pts = [...((t.lanes || {})[lane] || [])].sort((a, b) => a[0] - b[0]);
    if (pts.length < 3) return;
    const sel = t.notes.filter((n) => this.app.sel.has(n.id));
    const lo = sel.length ? Math.min(...sel.map((n) => n.tick)) : -Infinity, hi = sel.length ? Math.max(...sel.map((n) => n.tick + n.dur)) : Infinity;
    const win = this.app.project().ppq / 4;
    const out = pts.map(([tk, v]) => {
      if (tk < lo || tk > hi) return [tk, v];
      const near = pts.filter((q) => Math.abs(q[0] - tk) <= win);
      return [tk, Math.round(near.reduce((a, q) => a + q[1], 0) / near.length * 100) / 100];
    });
    this.app.edit(`smooth ${lane}`, (p) => { const tr = this.app.trackOf(p); tr.lanes = { ...(tr.lanes || {}), [lane]: out }; });
  }
  commit() {
    const d = this.drag; this.drag = null; if (!d || !d.pts.length) return;
    const lo = Math.min(...d.pts.map((p) => p[0])), hi = Math.max(...d.pts.map((p) => p[0]));
    const lane = this.lane;
    this.app.edit(d.erase ? `clear ${lane}` : `draw ${lane}`, (p) => {
      const t = this.app.trackOf(p); t.lanes = t.lanes || {};
      const keep = (t.lanes[lane] || []).filter((q) => q[0] < lo - 1 || q[0] > hi + 1);
      t.lanes[lane] = d.erase ? keep : [...keep, ...d.pts].sort((a, b) => a[0] - b[0]);
      if (!t.lanes[lane].length) delete t.lanes[lane];
    });
  }
  draw() {
    const cv = this.cv, dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
    if (!W || !H) return;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const css = getComputedStyle(document.body), c = (n) => css.getPropertyValue(n).trim(), s = this.spec();
    g.fillStyle = c('--bg'); g.fillRect(0, 0, W, H);
    g.strokeStyle = c('--line'); g.beginPath(); g.moveTo(KEYW, this.Yv(s.zero)); g.lineTo(W, this.Yv(s.zero)); g.stroke();
    g.fillStyle = c('--muted'); g.font = '10px Sora, sans-serif'; g.fillText(String(s.max), 4, 11); g.fillText(String(s.min), 4, H - 3);
    const t = this.app.track(); if (!t) return;
    let pts = [...((t.lanes || {})[this.lane] || [])];
    if (this.drag) {
      const lo = Math.min(...this.drag.pts.map((p) => p[0])), hi = Math.max(...this.drag.pts.map((p) => p[0]));
      pts = pts.filter((q) => q[0] < lo || q[0] > hi); if (!this.drag.erase) pts = [...pts, ...this.drag.pts];
      pts.sort((a, b) => a[0] - b[0]);
    }
    if (!pts.length) return;
    g.strokeStyle = c('--accent'); g.lineWidth = 2; g.beginPath();
    pts.forEach(([tk, v], i) => { const x = this.roll.X(tk), y = this.Yv(v); i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.stroke();
    g.fillStyle = c('--accent'); g.globalAlpha = 0.12; g.beginPath(); g.moveTo(this.roll.X(pts[0][0]), this.Yv(s.zero));
    pts.forEach(([tk, v]) => g.lineTo(this.roll.X(tk), this.Yv(v))); g.lineTo(this.roll.X(pts.at(-1)[0]), this.Yv(s.zero)); g.fill(); g.globalAlpha = 1;
  }
}
