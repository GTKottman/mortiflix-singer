// The piano roll: notes with their words inside, phonemes and the rendered pitch drawn over them.
import { tempoMap, ticksPerBar, syllables, uid, SCALES, groupSpan, trackNotes } from './model.js';

const KEYW = 52, RULER = 26;
const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const BLACK = new Set([1, 3, 6, 8, 10]);

export class Roll {
  constructor(canvas, app) {
    this.cv = canvas; this.app = app;
    this.x0 = 0; this.pxPerTick = 0.12; this.top = 76; this.rowH = 16;      // view: first tick, zoom, top pitch, row height
    this.drag = null; this.hover = null;
    canvas.addEventListener('mousedown', (e) => this.down(e));
    addEventListener('mousemove', (e) => this.move(e));
    addEventListener('mouseup', (e) => this.up(e));
    canvas.addEventListener('dblclick', (e) => this.dbl(e));
    canvas.addEventListener('wheel', (e) => this.wheel(e), { passive: false });
    canvas.addEventListener('contextmenu', (e) => { e.preventDefault(); const n = this.noteAt(e); if (n) this.app.edit('delete note', (p) => { const t = this.app.trackOf(p); t.notes = t.notes.filter((x) => x.id !== n.id); }); });
    new ResizeObserver(() => this.draw()).observe(canvas);
  }
  // geometry
  get W() { return this.cv.clientWidth; } get H() { return this.cv.clientHeight; }
  X(tick) { return KEYW + (tick - this.x0) * this.pxPerTick; }
  T(x) { return this.x0 + (x - KEYW) / this.pxPerTick; }
  Y(pitch) { return RULER + (this.top - pitch) * this.rowH; }
  P(y) { return Math.floor(this.top - (y - RULER) / this.rowH) + 1; }
  snap(t) { const s = this.app.snapTicks(); return s ? Math.round(t / s) * s : Math.round(t); }
  pos(e) { const r = this.cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
  notes() { return this.app.track()?.notes || []; }
  noteAt(e) {
    const { x, y } = this.pos(e); if (x < KEYW || y < RULER) return null;
    const t = this.T(x), p = this.P(y);
    return this.notes().find((n) => n.pitch === p && t >= n.tick && t <= n.tick + n.dur) || null;
  }
  scrollTo(tick) { this.x0 = Math.max(0, tick); this.draw(); }
  centerOn(notes) {
    if (!notes.length) return;
    const ps = notes.map((n) => n.pitch), ppq = this.app.project().ppq;
    const lo = Math.max(0, Math.min(...notes.map((n) => n.tick)) - ppq), hi = Math.max(...notes.map((n) => n.tick + n.dur)) + ppq;
    const span = Math.min(hi - lo, ppq * 4 * 12);                 // fit the part, at most 12 bars across
    this.pxPerTick = Math.max(0.03, Math.min(1.2, (this.W - KEYW - 20) / span));
    this.rowH = Math.max(14, Math.min(26, Math.floor((this.H - RULER) / (Math.max(...ps) - Math.min(...ps) + 14))));
    this.top = Math.max(...ps) + 6; this.x0 = lo;
    this.draw();
  }

  // group instances on the current track: [{ref, x1, x2, y1, y2}] in canvas pixels
  refBoxes() {
    const p = this.app.project(), t = this.app.track(); if (!t?.refs?.length || this.app.groupEdit) return [];
    return t.refs.map((r) => {
      const g = p.groups?.[r.group]; if (!g?.notes.length) return null;
      const ps = g.notes.map((n) => n.pitch + (r.transpose || 0));
      return { ref: r, g, x1: this.X(r.tick), x2: this.X(r.tick + groupSpan(g)), y1: this.Y(Math.max(...ps)) - 4, y2: this.Y(Math.min(...ps)) + this.rowH + 4 };
    }).filter(Boolean);
  }
  refAt(x, y) { const b = this.refBoxes().find((b) => x >= b.x1 && x <= b.x2 && y >= b.y1 && y <= b.y2); return b ? b.ref : null; }

  // ---- mouse ----
  down(e) {
    if (e.button !== 0) return;
    const { x, y } = this.pos(e), app = this.app, tool = app.tool;
    this.cv.focus?.();
    if (y < RULER && e.shiftKey) { const t0 = this.snap(Math.max(0, this.T(x))); this.drag = { kind: 'loop', a: t0, b: t0 }; return; }   // shift-drag: loop region
    if (y < RULER) { app.seek(Math.max(0, this.T(x))); this.drag = { kind: 'seek' }; return; }
    if (x < KEYW) { app.previewPitch(this.P(y)); return; }
    const n = this.noteAt(e);
    const ref = !n && this.refAt(x, y);
    if (ref && tool !== 'pitch') {                   // a group instance: select it, drag to move it
      app.sel.clear(); app.selRef = ref.id; app.changed('select');
      this.drag = { kind: 'ref', start: { x, y }, ref: ref.id, tick: ref.tick, tr: ref.transpose || 0, moved: false };
      return;
    }
    if (app.selRef) { app.selRef = null; app.changed('select'); }
    if (tool === 'erase') { if (n) app.edit('erase note', (p) => { const t = app.trackOf(p); t.notes = t.notes.filter((m) => m.id !== n.id); }); return; }
    if (tool === 'pitch') { this.drag = { kind: 'pitch', pts: [[this.T(x), this.pitchAtY(y)]] }; return; }
    if (n) {
      if (!app.sel.has(n.id)) { if (!e.shiftKey) app.sel.clear(); app.sel.add(n.id); }
      else if (e.shiftKey) { app.sel.delete(n.id); app.changed('select'); return; }
      const edge = this.X(n.tick + n.dur) - x < 7;
      this.drag = { kind: edge ? 'resize' : 'move', start: { x, y }, note: n, orig: this.notes().filter((m) => app.sel.has(m.id)).map((m) => ({ id: m.id, tick: m.tick, dur: m.dur, pitch: m.pitch })), moved: false };
      app.changed('select'); app.previewPitch(n.pitch);
      return;
    }
    if (tool === 'draw') {
      const pitch = this.P(y);
      const len = app.snapTicks() || app.project().ppq / 2;
      const note = { id: uid(), tick: Math.floor(this.T(x) / len) * len, dur: len, pitch, lyric: app.nextLyric(), vel: 64 };
      app.edit('add note', (p) => { app.trackOf(p).notes.push(note); });
      app.sel.clear(); app.sel.add(note.id);
      this.drag = { kind: 'resize', start: { x, y }, note, orig: [{ id: note.id, tick: note.tick, dur: note.dur, pitch }], moved: true, fresh: true };
      app.previewPitch(pitch);
      return;
    }
    if (!e.shiftKey) app.sel.clear();
    this.drag = { kind: 'box', a: { x, y }, b: { x, y } }; app.changed('select');
  }
  pitchAtY(y) { return this.top - (y - RULER) / this.rowH + 0.5; }
  move(e) {
    const d = this.drag; if (!d) { const n = this.cv.matches(':hover') ? this.noteAt(e) : null; const { x } = this.pos(e); this.cv.style.cursor = n && this.X(n.tick + n.dur) - x < 7 ? 'ew-resize' : this.app.tool === 'draw' ? 'crosshair' : this.app.tool === 'pitch' ? 'crosshair' : 'default'; return; }
    const { x, y } = this.pos(e), app = this.app;
    if (d.kind === 'seek') { app.seek(Math.max(0, this.T(x))); return; }
    if (d.kind === 'loop') { d.b = this.snap(Math.max(0, this.T(x))); this.draw(); return; }
    if (d.kind === 'box') { d.b = { x, y }; this.draw(); return; }
    if (d.kind === 'pitch') { d.pts.push([this.T(x), this.pitchAtY(y)]); this.draw(); return; }
    const dt = this.snap((x - d.start.x) / this.pxPerTick), dp = Math.round(-(y - d.start.y) / this.rowH);
    if (d.kind === 'ref') {
      const r = (app.track().refs || []).find((q) => q.id === d.ref);
      if (r) { r.tick = Math.max(0, d.tick + dt); r.transpose = d.tr + dp; }
      d.moved = true; this.draw(); return;
    }
    const live = this.notes();
    if (d.kind === 'move') {
      for (const o of d.orig) { const n = live.find((m) => m.id === o.id); if (n) { n.tick = Math.max(0, o.tick + dt); n.pitch = o.pitch + dp; } }
      if (dp && dp !== d.lastDp) { app.previewPitch(d.note.pitch); d.lastDp = dp; }
    } else {
      const min = Math.max(15, app.snapTicks() || 15);
      for (const o of d.orig) { const n = live.find((m) => m.id === o.id); if (n) n.dur = Math.max(min, o.dur + dt); }
    }
    d.moved = true; this.draw();
  }
  up(e) {
    const d = this.drag; this.drag = null; if (!d) return;
    const app = this.app;
    if (d.kind === 'loop') {
      const [a, b] = [Math.min(d.a, d.b), Math.max(d.a, d.b)];
      if (b - a >= 30) app.edit('loop region', (p) => { p.loop = { start: a, end: b, on: true }; });
      return;
    }
    if (d.kind === 'ref') {
      if (!d.moved) return;
      const r = (app.track().refs || []).find((q) => q.id === d.ref); if (!r) return;
      const final = { tick: r.tick, transpose: r.transpose }; r.tick = d.tick; r.transpose = d.tr;      // undoable, like note drags
      app.edit('move group', (p) => { const q = app.trackOf(p).refs.find((x) => x.id === d.ref); Object.assign(q, final); });
      return;
    }
    if (d.kind === 'box') {
      const [x1, x2] = [Math.min(d.a.x, d.b.x), Math.max(d.a.x, d.b.x)], [y1, y2] = [Math.min(d.a.y, d.b.y), Math.max(d.a.y, d.b.y)];
      for (const n of this.notes()) { const nx = this.X(n.tick), ny = this.Y(n.pitch); if (nx + 2 < x2 && this.X(n.tick + n.dur) > x1 && ny + this.rowH > y1 && ny < y2) app.sel.add(n.id); }
      app.changed('select'); return;
    }
    if (d.kind === 'pitch') {
      const pts = d.pts.filter((p) => p[0] >= 0); if (pts.length < 2) return;
      const lo = Math.min(...pts.map((p) => p[0])), hi = Math.max(...pts.map((p) => p[0]));
      app.edit('draw pitch', (p) => { const t = app.trackOf(p); t.pitch_draw = [...(t.pitch_draw || []).filter((q) => q[0] < lo || q[0] > hi), ...pts.map(([tk, m]) => [Math.round(tk), Math.round(m * 100) / 100])].sort((a, b) => a[0] - b[0]); });
      return;
    }
    if ((d.kind === 'move' || d.kind === 'resize') && d.moved) {
      // the live drag changed the notes directly: put the originals back, then apply once as an undoable edit
      const live = this.notes(), final = d.orig.map((o) => { const n = live.find((m) => m.id === o.id); return n && { id: o.id, tick: n.tick, dur: n.dur, pitch: n.pitch }; }).filter(Boolean);
      if (!d.fresh) for (const o of d.orig) { const n = live.find((m) => m.id === o.id); if (n) Object.assign(n, { tick: o.tick, dur: o.dur, pitch: o.pitch }); }
      app.edit(d.kind === 'move' ? 'move notes' : 'resize notes', (p) => { for (const f of final) { const n = app.trackOf(p).notes.find((m) => m.id === f.id); if (n) Object.assign(n, f); } });
    }
  }
  dbl(e) {
    const n = this.noteAt(e); if (!n) return;
    this.app.editLyric(n, { x: this.X(n.tick), y: this.Y(n.pitch), w: Math.max(70, n.dur * this.pxPerTick), h: this.rowH });
  }
  wheel(e) {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) { const { x } = this.pos(e), t = this.T(x); this.pxPerTick = Math.min(2, Math.max(0.01, this.pxPerTick * (e.deltaY < 0 ? 1.15 : 1 / 1.15))); this.x0 = Math.max(0, t - (x - KEYW) / this.pxPerTick); }
    else if (e.altKey) { this.rowH = Math.min(36, Math.max(8, this.rowH + (e.deltaY < 0 ? 1 : -1))); }
    else if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) { this.x0 = Math.max(0, this.x0 + (e.deltaX || e.deltaY) / this.pxPerTick); }
    else { this.top = Math.min(108, Math.max(30, this.top - Math.sign(e.deltaY) * 2)); }
    this.draw();
  }

  // ---- drawing ----
  draw() {
    const cv = this.cv, dpr = devicePixelRatio || 1, W = this.W, H = this.H;
    if (!W || !H) return;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const css = getComputedStyle(document.body), c = (n) => css.getPropertyValue(n).trim();
    const p = this.app.project(), t = this.app.track(), tm = tempoMap(p), bar = ticksPerBar(p), beat = p.ppq * 4 / p.time_sig[1];
    g.fillStyle = c('--bg'); g.fillRect(0, 0, W, H);
    // rows
    const key = p.key && SCALES[p.key.scale] ? new Set(SCALES[p.key.scale]) : null;
    for (let m = Math.ceil(this.top - (H - RULER) / this.rowH) - 1; m <= this.top; m++) {
      const y = this.Y(m), pc = ((m % 12) + 12) % 12;
      // with a key set, rows outside the scale are shaded (the scale's notes stay clear, its root is marked);
      // without one, the black keys are shaded as on a piano
      const out = key ? !key.has((pc - p.key.root + 12) % 12) : BLACK.has(pc);
      if (out) { g.fillStyle = key ? c('--line') : (c('--raise') || 'rgba(127,127,127,.06)'); g.globalAlpha = key ? 0.85 : 0.6; g.fillRect(KEYW, y, W, this.rowH); g.globalAlpha = 1; }
      if (key && pc === p.key.root) { g.fillStyle = c('--accent'); g.globalAlpha = 0.06; g.fillRect(KEYW, y, W, this.rowH); g.globalAlpha = 1; }
      g.strokeStyle = c('--line'); g.lineWidth = m % 12 === 0 ? 1 : 0.5; g.beginPath(); g.moveTo(KEYW, y + this.rowH); g.lineTo(W, y + this.rowH); g.stroke();
    }
    // grid: bars, beats, snap
    const t1 = this.T(W), snapT = this.app.snapTicks();
    const step = this.pxPerTick * beat < 12 ? bar : this.pxPerTick * (snapT || beat) < 10 ? beat : snapT || beat;
    for (let k = Math.floor(this.x0 / step) * step; k <= t1; k += step) {
      const x = this.X(k); g.strokeStyle = c('--line'); g.globalAlpha = k % bar === 0 ? 1 : k % beat === 0 ? 0.6 : 0.3; g.lineWidth = k % bar === 0 ? 1.2 : 0.6;
      g.beginPath(); g.moveTo(x, RULER); g.lineTo(x, H); g.stroke(); g.globalAlpha = 1;
    }
    // ruler
    g.fillStyle = c('--bg'); g.fillRect(0, 0, W, RULER); g.fillStyle = c('--muted'); g.font = '11px Sora, sans-serif';
    for (let k = Math.floor(this.x0 / bar) * bar; k <= t1; k += bar) { const x = this.X(k); if (x >= KEYW) g.fillText(String(k / bar + 1), x + 3, 16); }
    // loop region (shift-drag on the ruler; L turns it on and off) and markers
    const lp = this.drag?.kind === 'loop' ? { start: Math.min(this.drag.a, this.drag.b), end: Math.max(this.drag.a, this.drag.b), on: true } : p.loop;
    if (lp) { const x1 = Math.max(KEYW, this.X(lp.start)), x2 = this.X(lp.end); if (x2 > KEYW) { g.fillStyle = c('--accent'); g.globalAlpha = lp.on ? 0.28 : 0.1; g.fillRect(x1, 0, x2 - x1, RULER); g.globalAlpha = lp.on ? 0.05 : 0.02; g.fillRect(x1, RULER, x2 - x1, H); g.globalAlpha = 1; } }
    g.fillStyle = c('--ink'); for (const m of p.markers || []) { const x = this.X(m.tick); if (x >= KEYW && x <= W) { g.fillRect(x, 0, 1, RULER); g.fillText(m.name, x + 3, 9); } }
    g.fillStyle = c('--muted');
    // tempo changes after the first: their BPM on the ruler, in the accent colour
    g.fillStyle = c('--accent'); for (const tp of p.tempo) { if (!tp.tick) continue; const x = this.X(tp.tick); if (x >= KEYW && x <= W) { g.fillRect(x, 0, 1.5, RULER); g.fillText(`${+tp.bpm.toFixed(2)}`, x + 4, 24); } }
    g.strokeStyle = c('--line'); g.beginPath(); g.moveTo(0, RULER); g.lineTo(W, RULER); g.stroke();
    if (!t) return;
    const msToTick = (ms) => tm.toTick(ms);
    // other tracks, faint
    for (const o of p.tracks) { if (o.id === t.id) continue; g.fillStyle = c('--muted'); g.globalAlpha = 0.18; for (const n of o.notes) g.fillRect(this.X(n.tick), this.Y(n.pitch) + 3, n.dur * this.pxPerTick, this.rowH - 6); g.globalAlpha = 1; }
    // group instances: a labelled box with the group's notes inside, outlined
    const accentG = c('--accent');
    for (const b of this.refBoxes()) {
      if (b.x1 > W || b.x2 < KEYW) continue;
      const on = this.app.selRef === b.ref.id;
      g.fillStyle = accentG; g.globalAlpha = on ? 0.16 : 0.07; g.fillRect(b.x1, b.y1, b.x2 - b.x1, b.y2 - b.y1); g.globalAlpha = 1;
      g.strokeStyle = accentG; g.lineWidth = on ? 2 : 1; g.setLineDash([5, 3]); g.strokeRect(b.x1 + 0.5, b.y1 + 0.5, b.x2 - b.x1, b.y2 - b.y1); g.setLineDash([]);
      g.fillStyle = accentG; g.font = '11px Sora, sans-serif'; g.fillText(`${b.g.name}${b.ref.transpose ? ` ${b.ref.transpose > 0 ? '+' : ''}${b.ref.transpose}` : ''}`, b.x1 + 4, b.y1 - 3);
      for (const n of b.g.notes) {
        const x = this.X(n.tick + b.ref.tick), y = this.Y(n.pitch + (b.ref.transpose || 0)), w = Math.max(3, n.dur * this.pxPerTick);
        g.strokeStyle = accentG; g.lineWidth = 1; g.strokeRect(x + 0.5, y + 1.5, w - 1, this.rowH - 3);
        g.save(); g.beginPath(); g.rect(x, y, w, this.rowH); g.clip(); g.fillStyle = c('--ink'); g.globalAlpha = 0.8;
        g.font = `${Math.min(13, this.rowH - 3)}px Sora, sans-serif`; g.fillText(n.lyric || '', x + 4, y + this.rowH - 4); g.restore();
      }
    }
    // notes
    const accent = c('--accent'), ink = c('--ink');
    const tooMany = this.app.syllableTrouble();
    for (const n of t.notes) {
      const x = this.X(n.tick), y = this.Y(n.pitch), w = Math.max(3, n.dur * this.pxPerTick);
      if (x > W || x + w < KEYW) continue;
      const sel = this.app.sel.has(n.id);
      g.fillStyle = tooMany.has(n.id) ? '#e5484d' : accent; g.globalAlpha = sel ? 0.85 : 0.45; g.fillRect(x + 0.5, y + 1, w - 1, this.rowH - 2); g.globalAlpha = 1;
      if (sel) { g.strokeStyle = ink; g.lineWidth = 1.5; g.strokeRect(x + 0.5, y + 1, w - 1, this.rowH - 2); }
      g.save(); g.beginPath(); g.rect(x, y, w, this.rowH); g.clip();
      g.fillStyle = ink; g.font = `${Math.min(13, this.rowH - 3)}px Sora, sans-serif`; g.fillText(n.lyric || '', x + 4, y + this.rowH - 4); g.restore();
    }
    // phonemes and the rendered pitch from the last render
    const r = this.app.renders[t.id] || [];
    g.font = '10px Sora, sans-serif';
    const showPhones = this.pxPerTick > 0.2 && this.rowH >= 14;      // phonemes only when there is room to read them
    const allNotes = this.app.groupEdit ? t.notes : trackNotes(p, t);  // group copies' phonemes sit under their notes too
    for (const ph of r) {
      for (const [sym, s] of showPhones ? ph.phones || [] : []) {
        const x = this.X(msToTick(s)); if (x < KEYW || x > W) continue;
        const n = allNotes.find((m) => { const a = tm.toMs(m.tick); return s >= a - 400 && s < tm.toMs(m.tick + m.dur); });
        const y = n ? this.Y(n.pitch) + this.rowH + 10 : RULER + 12;
        g.fillStyle = c('--muted'); g.fillText(sym, x + 1, y);
        g.strokeStyle = c('--muted'); g.globalAlpha = 0.4; g.beginPath(); g.moveTo(x, y - 9); g.lineTo(x, y + 1); g.stroke(); g.globalAlpha = 1;
      }
      g.strokeStyle = ink; g.lineWidth = 1.4; g.beginPath(); let first = true;
      for (const [ms, midi] of ph.pitch || []) {          // the sung pitch, through the middle of each note's row
        const x = this.X(msToTick(ms)), y = this.Y(midi) + this.rowH / 2;
        if (x < KEYW - 20 || x > W + 20) { first = true; continue; }
        if (first) g.moveTo(x, y); else g.lineTo(x, y); first = false;
      }
      g.stroke();
    }
    // a drawn pitch line
    const drawn = this.drag?.kind === 'pitch' ? [...(t.pitch_draw || []), ...this.drag.pts].sort((a, b) => a[0] - b[0]) : t.pitch_draw || [];
    if (drawn.length) {
      g.strokeStyle = accent; g.lineWidth = 2; g.setLineDash([5, 3]); g.beginPath();
      drawn.forEach(([tk, m], i) => { const x = this.X(tk), y = this.Y(m) + this.rowH / 2; i && tk - drawn[i - 1][0] < 120 ? g.lineTo(x, y) : g.moveTo(x, y); });
      g.stroke(); g.setLineDash([]);
    }
    // box selection
    if (this.drag?.kind === 'box') { const d = this.drag; g.strokeStyle = accent; g.setLineDash([4, 3]); g.strokeRect(d.a.x, d.a.y, d.b.x - d.a.x, d.b.y - d.a.y); g.setLineDash([]); }
    // keyboard
    g.fillStyle = c('--bg'); g.fillRect(0, RULER, KEYW, H);
    for (let m = Math.ceil(this.top - (H - RULER) / this.rowH) - 1; m <= this.top; m++) {
      const y = this.Y(m), pc = ((m % 12) + 12) % 12;
      g.fillStyle = BLACK.has(pc) ? '#24212c' : '#e9e7ee'; g.fillRect(0, y + 0.5, KEYW - 2, this.rowH - 1);      // real key colours in both themes
      if (pc === 0 || this.rowH >= 18) { g.fillStyle = BLACK.has(pc) ? '#e9e7ee' : '#24212c'; g.font = '10px Sora, sans-serif'; g.fillText(`${NAMES[pc]}${Math.floor(m / 12) - 1}`, 4, y + this.rowH - 4); }
    }
    // voice range shading on the keyboard
    const range = this.app.voiceRange();
    if (range) { g.fillStyle = accent; g.globalAlpha = 0.25; g.fillRect(KEYW - 5, this.Y(range[1]), 4, (range[1] - range[0] + 1) * this.rowH); g.globalAlpha = 1; }
    // playhead
    const ph = this.X(this.app.playTick);
    if (ph >= KEYW && ph <= W) { g.strokeStyle = '#e5484d'; g.lineWidth = 1.5; g.beginPath(); g.moveTo(ph, 0); g.lineTo(ph, H); g.stroke(); }
  }
}
