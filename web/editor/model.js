// The project model: one JSON object (the .msing format), every edit a named step that can be undone.
export const PPQ = 480;
export const LANES = { pitch: { label: 'Pitch (cents)', min: -200, max: 200, zero: 0 }, energy: { label: 'Energy (dB)', min: -24, max: 12, zero: 0 },
  breathiness: { label: 'Breathiness (dB)', min: -24, max: 24, zero: 0 }, voicing: { label: 'Voicing (dB)', min: -48, max: 12, zero: 0 },
  tension: { label: 'Tension', min: -10, max: 10, zero: 0 }, gender: { label: 'Gender (lighter / darker)', min: -1, max: 1, zero: 0 },
  velocity: { label: 'Consonant speed', min: 0.5, max: 2, zero: 1 } };
export const uid = () => Math.random().toString(36).slice(2, 10);

export function newTrack(name = 'Lead', voice = 'SPORE') {
  return { id: uid(), name, voice, mode: 'Default', mute: false, solo: false, gain_db: 0, pan: 0, transpose: 0, notes: [], lanes: {}, pitch_draw: [], params: { expr: 1, correct: 1, steps: 20 } };
}
export function newProject(title = 'Untitled', bpm = 120) {
  return { version: 1, ppq: PPQ, title, tempo: [{ tick: 0, bpm }], time_sig: [4, 4], tracks: [newTrack()] };
}

export class History {
  constructor(project, onChange) { this.p = project; this.undoStack = []; this.redoStack = []; this.onChange = onChange; }
  snapshot() { return JSON.stringify(this.p); }
  // run fn(project) as one undoable step
  edit(label, fn) {
    const before = this.snapshot();
    fn(this.p);
    if (this.snapshot() === before) return;
    this.undoStack.push({ label, before }); if (this.undoStack.length > 500) this.undoStack.shift();
    this.redoStack = [];
    this.onChange?.(label);
  }
  replace(project, label = 'open') { this.p = project; this.undoStack = []; this.redoStack = []; this.onChange?.(label); }
  undo() { const s = this.undoStack.pop(); if (!s) return; this.redoStack.push({ label: s.label, before: this.snapshot() }); this.p = JSON.parse(s.before); this.onChange?.('undo'); }
  redo() { const s = this.redoStack.pop(); if (!s) return; this.undoStack.push({ label: s.label, before: this.snapshot() }); this.p = JSON.parse(s.before); this.onChange?.('redo'); }
}

// tempo map: ticks <-> ms
export function tempoMap(p) {
  const pts = [...p.tempo].sort((a, b) => a.tick - b.tick); if (pts[0].tick !== 0) pts.unshift({ tick: 0, bpm: pts[0].bpm });
  const ms = [0]; for (let i = 1; i < pts.length; i++) ms.push(ms[i - 1] + (pts[i].tick - pts[i - 1].tick) * 60000 / (pts[i - 1].bpm * p.ppq));
  const toMs = (tick) => { let i = 0; while (i + 1 < pts.length && pts[i + 1].tick <= tick) i++; return ms[i] + (tick - pts[i].tick) * 60000 / (pts[i].bpm * p.ppq); };
  const toTick = (t) => { let i = 0; while (i + 1 < pts.length && ms[i + 1] <= t) i++; return pts[i].tick + (t - ms[i]) * pts[i].bpm * p.ppq / 60000; };
  return { toMs, toTick };
}
export const ticksPerBar = (p) => p.ppq * 4 * p.time_sig[0] / p.time_sig[1];

// lyric tokens onto notes: "sun-rise" splits over two notes, "_" holds, "." silent
export function splitLyrics(text) {
  return text.replace(/,/g, ' ').split(/\s+/).filter(Boolean).flatMap((w) => (/^[^{]*-[^{-]/.test(w) ? w.split(/-(?=.)/).map((s, i, a) => (i < a.length - 1 ? `${s}-` : s)) : [w]));
}

// syllables in a word (vowel groups, silent final e): for the red "too many syllables" warning
export function syllables(word, lang = 'en') {
  if (lang === 'ja') {        // Japanese: one mora per note: every kana (small ya/yu/yo and small tsu ride on the one before) or romaji vowel / syllabic n
    if (/[\u3040-\u30ff]/.test(word)) return Math.max(1, [...word].filter((c) => /[\u3040-\u30ff]/.test(c) && !'ゃゅょャュョっッー'.includes(c)).length);
    const w = word.toLowerCase().replace(/[^a-z]/g, '');
    return Math.max(1, (w.match(/[aiueo]/g) || []).length + (w.match(/n(?![aiueoy])/g) || []).length);
  }
  if (lang === 'es' || lang === 'it') {    // Spanish/Italian: every vowel sings, except i/u gliding next to another vowel
    const w = word.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z]/g, '').replace(/[qg]u(?=[aeio])/g, 'q');
    const v = (w.match(/[aeiou]/g) || []).length, glides = (w.match(/[iu](?=[aeo])|(?<=[aeo])[iu](?![aeiou])/g) || []).length;
    return Math.max(1, v - glides);
  }
  if (lang === 'la') {        // Latin: every vowel sings, except the digraphs ae / oe / au
    const w = word.toLowerCase().replace(/[^a-z]/g, '').replace(/ae|oe|au/g, 'a').replace(/qu/g, 'q');
    return Math.max(1, (w.match(/[aeiouy]/g) || []).length);
  }
  let w = word.toLowerCase().replace(/[^a-z]/g, ''); if (!w) return 0; if (w.length <= 3) return 1;
  w = w.replace(/([^aeiouy])ed$/, (m, c) => ('td'.includes(c) ? m : c)).replace(/([^aeiouy])es$/, (m, c) => ('sxzcg'.includes(c) ? m : `${c}e`)).replace(/(?:[^laeiouy]e|[aeiouy]le)$/, (m) => m.slice(0, -1)).replace(/^y/, '');
  return Math.max(1, (w.match(/[aeiouy]+/g) || []).length);
}

// scales for the piano roll's key highlight: semitones above the root
export const SCALES = {
  major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10], dorian: [0, 2, 3, 5, 7, 9, 10], mixolydian: [0, 2, 4, 5, 7, 9, 10],
  'harmonic minor': [0, 2, 3, 5, 7, 8, 11], 'pentatonic major': [0, 2, 4, 7, 9], 'pentatonic minor': [0, 3, 5, 7, 10], blues: [0, 3, 5, 6, 7, 10],
};

// note groups: a track's own notes plus every instance of a group it places (ids "<ref>~<note>")
export function trackNotes(p, t) {
  const out = [...(t.notes || [])];
  for (const r of t.refs || []) {
    const g = p.groups?.[r.group]; if (!g) continue;
    for (const n of g.notes) out.push({ ...n, id: `${r.id}~${n.id}`, tick: n.tick + r.tick, pitch: n.pitch + (r.transpose || 0), ref: r.id });
  }
  return out;
}
export function groupSpan(g) { return g.notes.length ? Math.max(...g.notes.map((n) => n.tick + n.dur)) : 0; }

// meters: time_sig from bar 0, then project.meters = [{bar (0-based), num, den}] -> segments with their start ticks
export function barSegments(p) {
  const segs = [{ bar: 0, tick: 0, num: p.time_sig[0], den: p.time_sig[1] }];
  for (const m of [...(p.meters || [])].sort((a, b) => a.bar - b.bar)) {
    const l = segs[segs.length - 1]; if (m.bar <= l.bar) continue;
    segs.push({ bar: m.bar, tick: l.tick + (m.bar - l.bar) * p.ppq * 4 * l.num / l.den, num: m.num, den: m.den });
  }
  return segs;
}
// the bar a tick is in: { index (0-based), start, len, num, den, beat }
export function barAt(p, tick) {
  const segs = barSegments(p); let s = segs[0];
  for (const x of segs) if (x.tick <= tick) s = x;
  const len = p.ppq * 4 * s.num / s.den, k = Math.floor((tick - s.tick) / len);
  return { index: s.bar + k, start: s.tick + k * len, len, num: s.num, den: s.den, beat: p.ppq * 4 / s.den };
}
// bar number (1-based, may be fractional) <-> tick
export function barToTick(p, bar) {
  const i = bar - 1, segs = barSegments(p); let s = segs[0];
  for (const x of segs) if (x.bar <= i) s = x;
  return Math.round(s.tick + (i - s.bar) * p.ppq * 4 * s.num / s.den);
}
export function tickToBar(p, tick) { const b = barAt(p, tick); return b.index + 1 + (tick - b.start) / b.len; }

// a word cut into its syllables for singing ("sunrise" -> ["sun-", "rise"]): vowel groups, with V-CV and VC-CV
// splits (th/sh/ch/ph/wh/ck/ng stay together); as many parts as syllables() counts
export function syllabify(word, lang = 'en') {
  const n = syllables(word, lang); if (n <= 1) return [word];
  const w = word, lower = w.toLowerCase(), V = /[aeiouy]/;
  const groups = []; let i = 0;
  while (i < lower.length) { if (V.test(lower[i]) && !(lower[i] === 'y' && i === 0)) { const a = i; while (i < lower.length && V.test(lower[i])) i++; groups.push([a, i]); } else i++; }
  const cuts = [];
  for (let g = 0; g + 1 < groups.length && cuts.length < n - 1; g++) {
    const a = groups[g][1], b = groups[g + 1][0], cons = lower.slice(a, b);
    if (b === lower.length - 1 && lower.endsWith('e')) break;         // a silent final e is no syllable
    let cut = cons.length <= 1 ? a : a + 1;
    if (cons.length >= 4 && /^(str|spr|scr|spl|thr|shr)$/.test(cons.slice(-3))) cut = b - 3;
    else if (cons.length >= 3) cut = /^(bl|br|cl|cr|dr|fl|fr|gl|gr|pl|pr|sc|sk|sl|sm|sn|sp|st|sw|tr|tw|wr|kn|thr|str)$/.test(cons.slice(-2)) ? b - 2 : b - 1;
    if (cons.length >= 2 && /^(th|sh|ch|ph|wh|ck|ng)/.test(cons.slice(0, 2)) && cons.length === 2) cut = a;
    if (cons.length >= 2 && /^(ck|ng)$/.test(cons.slice(0, 2))) cut = a + 2;
    cuts.push(cut);
  }
  const parts = []; let last = 0;
  for (const c of cuts) { parts.push(w.slice(last, c)); last = c; }
  parts.push(w.slice(last));
  return parts.filter(Boolean).map((x, k, all) => (k < all.length - 1 ? `${x}-` : x));
}
