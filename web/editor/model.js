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
export function syllables(word) {
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
