// Mortiflix Singer editor: one screen (tracks, piano roll with words on notes, lanes, inspector), rendering through
// the singer service phrase by phrase while you edit.
import { History, newProject, newTrack, LANES, tempoMap, splitLyrics, syllables, uid, PPQ, SCALES, ticksPerBar, groupSpan } from './model.js';
import { Roll } from './roll.js';
import { Lanes } from './lanes.js';
import { Player } from './player.js';

const API = '/api/singer';
const $ = (id) => document.getElementById(id);
const post = (path, body, raw = false) => fetch(API + path, { method: 'POST', headers: { 'x-mortiflix': '1', 'content-type': raw ? 'application/octet-stream' : 'application/json' }, body: raw ? body : JSON.stringify(body) });
const store = { get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }, set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const midiOf = (s) => { const m = /^([A-G]#?)(-?\d)$/.exec(s || ''); return m ? 12 * (Number(m[2]) + 1) + NAMES.indexOf(m[1]) : null; };

const app = {
  api: API, history: null, sel: new Set(), tool: 'select', renders: {}, playTick: 0, guide: true, trackId: null, voices: [], modes: [], name: null, dirty: false,
  project() { return this.history.p; },
  // while a group is being edited, "the track" is the group (its notes at their own times, from 0)
  track() { const p = this.project(); if (this.groupEdit && p.groups?.[this.groupEdit]) return p.groups[this.groupEdit]; return p.tracks.find((t) => t.id === this.trackId) || p.tracks[0]; },
  trackOf(p) { if (this.groupEdit && p.groups?.[this.groupEdit]) return p.groups[this.groupEdit]; return p.tracks.find((t) => t.id === this.trackId) || p.tracks[0]; },
  groupEdit: null, selRef: null,
  edit(label, fn) { this.history.edit(label, fn); },
  changed(what) { draw(); inspector(); },
  snapTicks() { const v = Number($('snap').value); return v === 0 ? 0 : v === 3 ? PPQ / 3 : PPQ / v; },
  seek(tick) { this.playTick = tick; if (player.playing) player.play(tick); draw(); },
  onPlayhead(tick) { this.playTick = tick; draw(); },
  previewPitch(m) { player.preview(m + (this.track()?.transpose || 0)); },
  nextLyric() { return 'la'; },
  voiceRange() { const v = this.voices.find((x) => x.name === this.track()?.voice); return v?.range ? [midiOf(v.range[0]) - (this.track().transpose || 0), midiOf(v.range[1]) - (this.track().transpose || 0)] : null; },
  // notes whose word has more syllables than notes to carry them (the "chrome size" problem), shown red
  syllableTrouble() {
    const bad = new Set(), t = this.track(); if (!t) return bad;
    const ns = [...t.notes].sort((a, b) => a.tick - b.tick);
    for (let i = 0; i < ns.length; i++) {
      const ly = ns[i].lyric || ''; if (['_', '+', '.', 'br'].includes(ly) || /\{/.test(ly)) continue;
      if ((i > 0 && (ns[i - 1].lyric || '').endsWith('-'))) continue;
      const group = [ns[i]]; let j = i; while ((ns[j].lyric || '').endsWith('-') && j + 1 < ns.length) group.push(ns[++j]);
      const word = group.map((n) => (n.lyric || '').replace(/-$/, '')).join('');
      if (syllables(word) > group.length) group.forEach((n) => bad.add(n.id));
    }
    return bad;
  },
  editLyric(note, box) {
    const inp = $('lyric-edit'), r = $('roll').getBoundingClientRect();
    Object.assign(inp.style, { left: `${r.left + box.x}px`, top: `${r.top + box.y - 2}px`, width: `${box.w}px`, height: `${box.h + 4}px` });
    inp.hidden = false; inp.value = note.lyric || ''; inp.focus(); inp.select();
    const done = (save) => {
      inp.hidden = true; inp.onkeydown = null; inp.onblur = null;
      if (save && inp.value.trim() !== note.lyric) this.edit('lyric', (p) => { const n = this.trackOf(p).notes.find((m) => m.id === note.id); if (n) n.lyric = inp.value.trim() || 'la'; });
      $('roll').focus();
    };
    inp.onkeydown = (e) => {
      if (e.key === 'Enter') done(true);
      else if (e.key === 'Escape') done(false);
      else if (e.key === 'Tab') {                       // Tab: save and type the next note's word
        e.preventDefault(); done(true);
        const ns = [...this.track().notes].sort((a, b) => a.tick - b.tick), k = ns.findIndex((m) => m.id === note.id) + (e.shiftKey ? -1 : 1);
        if (ns[k]) { this.sel.clear(); this.sel.add(ns[k].id); this.editLyric(ns[k], { x: roll.X(ns[k].tick), y: roll.Y(ns[k].pitch), w: Math.max(70, ns[k].dur * roll.pxPerTick), h: roll.rowH }); }
      }
    };
    inp.onblur = () => done(true);
  },
};

const player = new Player(app);
let roll, lanes;

// ---- rendering: auto (preview quality, a moment after you stop editing) and on demand (final) ----
let renderTimer = null, renderSeq = 0;
function scheduleRender() { clearTimeout(renderTimer); if ($('auto').checked) renderTimer = setTimeout(() => render('preview'), 900); }
async function render(quality = 'final') {
  const seq = ++renderSeq, p = JSON.parse(JSON.stringify(app.project()));
  if (!p.tracks.some((t) => t.notes.length)) { status(''); return; }
  status(quality === 'final' ? 'Rendering (final)…' : 'Rendering…');
  try {
    const r = await post('/render', { project: p, quality, name: app.name });
    const d = await r.json(); if (!r.ok) throw new Error(d.error || r.statusText);
    if (seq !== renderSeq) return;
    app.renders = d.tracks;
    const n = Object.values(d.tracks).reduce((a, x) => a + x.length, 0);
    status(`${n} phrase${n === 1 ? '' : 's'} rendered${quality === 'preview' ? ' (preview)' : ''}`);
    draw();
  } catch (e) { status(`Render failed: ${e.message}`); }
}
function status(s) { $('status').textContent = s; }

// ---- retakes: a new random draw of the phrase a note is in (kept by number, so you can go back) ----
function phraseOf(n) { return (app.renders[app.track().id] || []).find((ph) => (ph.note_ids || []).includes(n.id)); }
function retake(n, how) {
  const ph = phraseOf(n); if (!ph) { status('Render first, then retake'); return; }
  app.edit(how === 0 ? 'first take' : 'retake', (p) => { const t = app.trackOf(p); t.takes = t.takes || {}; t.takes[String(ph.first_tick)] = how === 0 ? 0 : (t.takes[String(ph.first_tick)] || 0) + 1; });
  clearTimeout(renderTimer); render('final');
}

// ---- checks: every word heard, every note measured; a click jumps to the note ----
async function check() {
  status('Checking: hearing every phrase…');
  const r = await post('/check', { project: app.project(), track: app.track().id });
  const d = await r.json(); if (!r.ok) { status(`Check failed: ${d.error}`); return; }
  const res = d.tracks[app.track().id] || { words: [], tuning: [], summary: {} }, box = $('checks');
  box.hidden = false; box.textContent = '';
  const h = document.createElement('div'); h.className = 'pane-head'; h.textContent = 'Checks'; box.append(h);
  const sum = document.createElement('p'); sum.className = 'muted';
  sum.textContent = `${res.summary.words - res.summary.unclear} of ${res.summary.words} words clear · ${res.summary.off_notes} note${res.summary.off_notes === 1 ? '' : 's'} more than 20 cents off`;
  box.append(sum);
  const item = (text, ids, bad) => { const el = document.createElement('div'); el.className = `chk${bad ? ' bad' : ''}`; el.textContent = text; el.onclick = () => { app.sel = new Set(ids); const n = app.track().notes.find((m) => m.id === ids[0]); if (n) roll.scrollTo(Math.max(0, n.tick - app.project().ppq * 2)); changed('select'); }; box.append(el); };
  for (const w of res.words.filter((x) => !x.ok)) item(`"${w.word}" unclear: heard "${w.heard}"`, w.notes, true);
  for (const t of res.tuning) item(`${t.cents > 0 ? '+' : ''}${t.cents} cents`, [t.note], Math.abs(t.cents) > 50);
  if (!res.words.some((x) => !x.ok) && !res.tuning.length) item('Every word clear, every note in tune.', [], false);
  status('Checked');
}

// ---- phoneme timing: each phoneme of the word gets a length (100% = the voice's own); stored on the word's first note ----
function wordOf(n) {
  const ns = [...app.track().notes].sort((a, b) => a.tick - b.tick); let i = ns.findIndex((m) => m.id === n.id);
  if (i < 0 || /^[_+.]$|^br$/i.test(n.lyric || '')) return null;
  while (i > 0 && (ns[i - 1].lyric || '').endsWith('-')) i--;
  const first = ns[i]; let text = '';
  for (let k = i; k < ns.length; k++) { const ly = ns[k].lyric || 'la'; text += ly.replace(/-$/, ''); if (!ly.endsWith('-')) break; }
  return { first, text };
}
async function phonemeTiming(n) {
  const w = wordOf(n), box = $('i-timing'); if (!w || !box) return;
  let phs = w.first.phonemes ? w.first.phonemes.split(/\s+/) : null;
  if (!phs) {
    const d = await (await post('/phonemize', { voice: app.track().voice, words: [w.text] })).json();
    phs = Object.values(d.phonemes || {})[0] || [];
  }
  if (!phs.length || !$('i-timing')) return;
  const cur = Array.isArray(w.first.ph_scale) && w.first.ph_scale.length === phs.length ? w.first.ph_scale : phs.map(() => 1);
  box.textContent = '';
  const h = document.createElement('div'); h.className = 'muted'; h.textContent = `Phoneme lengths for "${w.text}" (%)`; box.append(h);
  const row = document.createElement('div'); row.className = 'timing-row';
  phs.forEach((ph, i) => {
    const l = document.createElement('label'); l.textContent = ph;
    const inp = document.createElement('input'); inp.type = 'number'; inp.min = '10'; inp.max = '400'; inp.step = '10'; inp.value = Math.round(cur[i] * 100);
    inp.onchange = () => app.edit('phoneme length', (p) => {
      const f = app.trackOf(p).notes.find((m) => m.id === w.first.id); if (!f) return;
      const next = [...cur]; next[i] = Math.min(400, Math.max(10, Number(inp.value) || 100)) / 100;
      f.ph_scale = next.every((x) => x === 1) ? null : next;
    });
    l.append(inp); row.append(l);
  });
  box.append(row);
  if (w.first.ph_scale) { const r = document.createElement('button'); r.className = 'btn tiny'; r.textContent = 'Reset lengths'; r.onclick = () => app.edit('phoneme length', (p) => { const f = app.trackOf(p).notes.find((m) => m.id === w.first.id); if (f) f.ph_scale = null; }); box.append(r); }
}

// ---- MIDI keyboard step input: with "MIDI in" on, each key played adds a note at the playhead (the snap length,
// or as long as the key is held when the snap is off) and moves the playhead on; a chord keeps its top note ----
const midiIn = { access: null, held: new Map(), on: false };
async function toggleMidi() {
  midiIn.on = !midiIn.on; $('midi').classList.toggle('on', midiIn.on);
  if (!midiIn.on) { status('MIDI input off'); return; }
  if (!navigator.requestMIDIAccess) { status('This browser has no MIDI access'); midiIn.on = false; $('midi').classList.remove('on'); return; }
  try { midiIn.access = midiIn.access || await navigator.requestMIDIAccess(); } catch { status('MIDI access was refused'); midiIn.on = false; $('midi').classList.remove('on'); return; }
  const hook = () => { for (const i of midiIn.access.inputs.values()) i.onmidimessage = onMidi; };
  hook(); midiIn.access.onstatechange = hook;
  const names = [...midiIn.access.inputs.values()].map((i) => i.name);
  status(names.length ? `MIDI input: ${names.join(', ')}. Play to add notes at the playhead.` : 'MIDI input on: no keyboard connected');
}
function onMidi(e) {
  if (!midiIn.on) return;
  const [st, note, vel] = e.data, kind = st & 0xf0;
  if (kind === 0x90 && vel > 0) {
    player.preview(note);
    const now = performance.now(), chord = midiIn.last && now - midiIn.last.at < 40;   // keys within 40 ms = one chord
    const at = chord ? midiIn.last.tick : app.playTick;
    midiIn.last = { tick: at, at: now };
    midiIn.held.set(note, { tick: at, at: now, vel });
    if (app.snapTicks()) stepNote(note, app.snapTicks(), vel, at);
  } else if ((kind === 0x80 || (kind === 0x90 && vel === 0)) && midiIn.held.has(note)) {
    const h = midiIn.held.get(note); midiIn.held.delete(note);
    if (!app.snapTicks()) {               // free length: as long as the key was held, at the song tempo
      const ms = performance.now() - h.at, tm = tempoMap(app.project());
      stepNote(note, Math.max(PPQ / 8, Math.round(tm.toTick(tm.toMs(h.tick) + ms) - h.tick)), h.vel, h.tick);
    }
  }
}
function stepNote(pitch, dur, vel, at = app.playTick) {
  const t = app.track(), clash = t.notes.find((n) => n.tick === at);
  if (clash && clash.pitch >= pitch) return;                       // a chord: the top note is the melody
  app.edit('MIDI note', (p) => {
    const tr = app.trackOf(p); tr.notes = tr.notes.filter((n) => n.tick !== at);
    tr.notes.push({ id: uid(), tick: at, dur, pitch, lyric: 'la', vel: Math.round(vel) });
  });
  app.seek(at + dur);
}

// ---- note groups: make, place, edit (every instance follows), ungroup ----
function makeGroup() {
  const t = app.track(), sel = t.notes.filter((n) => app.sel.has(n.id));
  if (app.groupEdit || sel.length < 1) { status('Select the notes to group first'); return; }
  const p = app.project(), bar = ticksPerBar(p), t0 = Math.floor(Math.min(...sel.map((n) => n.tick)) / bar) * bar;   // groups start on a bar
  const gid = uid(), rid = uid(), name = `Group ${Object.keys(p.groups || {}).length + 1}`;
  app.edit('make group', (q) => {
    const tr = app.trackOf(q); q.groups = q.groups || {};
    q.groups[gid] = { id: gid, name, voice: tr.voice, notes: sel.map((n) => ({ ...n, tick: n.tick - t0 })) };
    tr.notes = tr.notes.filter((n) => !app.sel.has(n.id)); tr.refs = [...(tr.refs || []), { id: rid, group: gid, tick: t0, transpose: 0 }];
  });
  app.sel.clear(); app.selRef = rid; changed('select'); status(`Made "${name}": duplicate it to reuse it; edit it once and every copy follows`);
}
function refOf(id) { return (app.project().tracks.flatMap((t) => (t.refs || []).map((r) => ({ t, r })))).find((x) => x.r.id === id); }
function groupPanel(box) {
  const x = refOf(app.selRef); if (!x) return false;
  const p = app.project(), g = p.groups[x.r.group], bar = ticksPerBar(p), uses = p.tracks.reduce((a, t) => a + (t.refs || []).filter((r) => r.group === g.id).length, 0);
  box.innerHTML = `<h3>Group</h3><div class="kv"><label>Name</label><input id="g-name"><label>At bar</label><input id="g-bar" type="number" min="1" step="0.25">
    <label>Transpose</label><input id="g-tr" type="number" step="1"></div><p class="muted" id="g-uses"></p>
    <p><button id="g-edit" class="btn tiny">Edit group</button> <button id="g-dup" class="btn tiny">Duplicate</button> <button id="g-un" class="btn tiny">Ungroup</button> <button id="g-del" class="btn tiny">Delete</button></p>`;
  $('g-name').value = g.name; $('g-bar').value = +(x.r.tick / bar + 1).toFixed(2); $('g-tr').value = x.r.transpose || 0;
  $('g-uses').textContent = `${g.notes.length} notes · used ${uses} time${uses === 1 ? '' : 's'}`;
  const setR = (label, fn) => app.edit(label, (q) => { const r = q.tracks.flatMap((t) => t.refs || []).find((r) => r.id === app.selRef); if (r) fn(r, q); });
  $('g-name').onchange = (e) => app.edit('rename group', (q) => { q.groups[g.id].name = e.target.value || g.name; });
  $('g-bar').onchange = (e) => setR('move group', (r) => { r.tick = Math.max(0, Math.round((Number(e.target.value) - 1) * bar)); });
  $('g-tr').onchange = (e) => setR('transpose group', (r) => { r.transpose = Number(e.target.value) || 0; });
  $('g-dup').onclick = () => { const id = uid(); app.edit('duplicate group', (q) => { const tr = q.tracks.find((t) => (t.refs || []).some((r) => r.id === app.selRef)); const r = tr.refs.find((r) => r.id === app.selRef); tr.refs.push({ ...r, id, tick: r.tick + Math.ceil(groupSpan(g) / bar) * bar }); }); app.selRef = id; changed('select'); };
  $('g-un').onclick = () => app.edit('ungroup', (q) => {
    const tr = q.tracks.find((t) => (t.refs || []).some((r) => r.id === app.selRef)), r = tr.refs.find((r) => r.id === app.selRef);
    tr.notes.push(...q.groups[r.group].notes.map((n) => ({ ...n, id: uid(), tick: n.tick + r.tick, pitch: n.pitch + (r.transpose || 0) })));
    tr.refs = tr.refs.filter((z) => z.id !== r.id); if (!q.tracks.some((t) => (t.refs || []).some((z) => z.group === r.group))) delete q.groups[r.group];
    app.selRef = null;
  });
  $('g-del').onclick = () => app.edit('delete group copy', (q) => { for (const t of q.tracks) t.refs = (t.refs || []).filter((r) => r.id !== app.selRef); app.selRef = null; });
  $('g-edit').onclick = () => enterGroup(g.id);
  return true;
}
function enterGroup(gid) {
  app.groupEdit = gid; app.selRef = null; app.sel.clear(); roll.scrollTo(0);
  $('group-bar').hidden = false; $('group-name').textContent = app.project().groups[gid].name; changed('select');
}
function leaveGroup() { app.groupEdit = null; app.sel.clear(); $('group-bar').hidden = true; changed('select'); scheduleRender(); }

// ---- drawing the side panes ----
function draw() { roll?.draw(); lanes?.draw(); }
function tracks() {
  const p = app.project(), box = $('tracks'); box.textContent = '';
  for (const t of p.tracks) {
    const el = document.createElement('div'); el.className = `track${t.id === app.track().id ? ' on' : ''}`;
    el.innerHTML = `<input class="name" value=""><div class="row"><select class="voice"></select><select class="mode"></select><label class="mstr-l" title="how strongly the vocal mode is applied">Strength <input class="mstr num" type="number" min="0" max="200" step="10">%</label></div>
      <div class="row"><span class="ms m" title="mute">M</span><span class="ms s" title="solo">S</span>
      <label title="volume in dB">dB <input class="gain num" type="number" step="0.5"></label>
      <label title="move the part by octaves (semitones)">Shift <input class="tr num" type="number" step="12"></label></div>`;
    el.querySelector('.name').value = t.name;
    const vs = el.querySelector('.voice'); for (const v of app.voices.length ? app.voices : [{ name: t.voice }]) vs.add(new Option(v.name, v.name, false, v.name === t.voice));
    const ms = el.querySelector('.mode'); for (const m of app.modes) ms.add(new Option(m, m, false, m === t.mode));
    el.querySelector('.m').classList.toggle('on', !!t.mute); el.querySelector('.s').classList.toggle('on', !!t.solo);
    el.querySelector('.gain').value = t.gain_db || 0; el.querySelector('.tr').value = t.transpose || 0;
    const set = (label, k, v) => app.edit(label, (q) => { q.tracks.find((x) => x.id === t.id)[k] = v; });
    el.onclick = (e) => { if (e.target.closest('input,select,.ms')) return; app.trackId = t.id; app.sel.clear(); tracks(); draw(); inspector(); };
    el.querySelector('.name').onchange = (e) => set('rename track', 'name', e.target.value);
    vs.onchange = (e) => set('voice', 'voice', e.target.value);
    ms.onchange = (e) => set('vocal mode', 'mode', e.target.value);
    const str = el.querySelector('.mstr'); str.value = Math.round((t.mode_strength ?? 1) * 100); el.querySelector('.mstr-l').hidden = (t.mode || 'Default') === 'Default';
    str.onchange = (e) => set('mode strength', 'mode_strength', Number(e.target.value) / 100);
    el.querySelector('.m').onclick = () => set('mute', 'mute', !t.mute);
    el.querySelector('.s').onclick = () => set('solo', 'solo', !t.solo);
    el.querySelector('.gain').onchange = (e) => set('volume', 'gain_db', Number(e.target.value));
    el.querySelector('.tr').onchange = (e) => set('octave', 'transpose', Number(e.target.value));
    box.append(el);
  }
}
function tempoPane() {
  const p = app.project(), box = $('tempo'), bar = ticksPerBar(p); box.textContent = '';
  const marks = [...p.tempo].sort((a, b) => a.tick - b.tick).filter((t) => t.tick > 0);
  for (const tp of marks) {
    const row = document.createElement('div'); row.className = 'row';
    const lab = document.createElement('span'); lab.textContent = `Bar ${+(tp.tick / bar + 1).toFixed(2)}`;
    const bpm = document.createElement('input'); bpm.type = 'number'; bpm.className = 'num'; bpm.step = '0.1'; bpm.min = '20'; bpm.max = '300'; bpm.value = tp.bpm;
    bpm.onchange = () => app.edit('tempo change', (q) => { const m = q.tempo.find((x) => x.tick === tp.tick); if (m) m.bpm = Number(bpm.value) || m.bpm; });
    const rm = document.createElement('button'); rm.className = 'btn tiny'; rm.textContent = '×'; rm.title = 'remove this tempo change';
    rm.onclick = () => app.edit('remove tempo change', (q) => { q.tempo = q.tempo.filter((x) => x.tick !== tp.tick); });
    row.append(lab, bpm, document.createTextNode('BPM'), rm); box.append(row);
  }
  const add = document.createElement('div'); add.className = 'row';
  const at = document.createElement('input'); at.type = 'number'; at.className = 'num'; at.min = '2'; at.step = '1'; at.value = Math.max(2, Math.floor(app.playTick / bar) + 1); at.title = 'bar';
  const nb = document.createElement('input'); nb.type = 'number'; nb.className = 'num'; nb.step = '0.1'; nb.value = p.tempo[0].bpm; nb.title = 'BPM';
  const go = document.createElement('button'); go.className = 'btn tiny'; go.textContent = 'Add';
  go.onclick = () => { const tick = Math.round((Math.max(2, Number(at.value)) - 1) * bar); app.edit('tempo change', (q) => { q.tempo = q.tempo.filter((x) => x.tick !== tick); q.tempo.push({ tick, bpm: Number(nb.value) || q.tempo[0].bpm }); q.tempo.sort((a, b) => a.tick - b.tick); }); };
  add.append(document.createTextNode('At bar'), at, nb, go); box.append(add);
}
function backing() {
  const box = $('backing'), bk = app.project().backing; box.textContent = '';
  const pick = document.createElement('label'); pick.className = 'btn tiny'; pick.textContent = bk ? 'Replace' : 'Add music to sing against';
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'audio/*'; inp.hidden = true; pick.append(inp);
  inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return; status(`Loading ${f.name}…`);
    const r = await post(`/backing?filename=${encodeURIComponent(f.name)}`, await f.arrayBuffer(), true), d = await r.json();
    if (!r.ok) { status(`Backing track failed: ${d.error}`); return; }
    app.edit('backing track', (p) => { p.backing = { file: d.file, name: d.name, gain_db: p.backing?.gain_db ?? -6, offset_ms: p.backing?.offset_ms ?? 0, mute: false }; });
    status(`Backing track: ${d.name}`);
  };
  if (!bk) { box.append(pick); return; }
  const el = document.createElement('div'); el.className = 'track';
  el.innerHTML = `<div class="name"></div><div class="row"><span class="ms m" title="mute">M</span>
    <label title="volume in dB">dB <input class="gain num" type="number" step="0.5"></label>
    <label title="move it later (+) or earlier (−) against the vocals, ms">Offset <input class="off num" type="number" step="10"></label></div>`;
  el.querySelector('.name').textContent = bk.name;
  el.querySelector('.m').classList.toggle('on', !!bk.mute);
  el.querySelector('.gain').value = bk.gain_db ?? 0; el.querySelector('.off').value = bk.offset_ms ?? 0;
  const set = (label, k, v) => app.edit(label, (p) => { p.backing[k] = v; });
  el.querySelector('.m').onclick = () => set('mute backing', 'mute', !bk.mute);
  el.querySelector('.gain').onchange = (e) => set('backing volume', 'gain_db', Number(e.target.value));
  el.querySelector('.off').onchange = (e) => set('backing offset', 'offset_ms', Number(e.target.value));
  const rm = document.createElement('button'); rm.className = 'btn tiny'; rm.textContent = 'Remove';
  rm.onclick = () => app.edit('remove backing', (p) => { delete p.backing; });
  const row = document.createElement('div'); row.className = 'row'; row.append(pick, rm); el.append(row);
  box.append(el);
}
function inspector() {
  const box = $('inspector'), t = app.track(); box.textContent = '';
  if (app.selRef && groupPanel(box)) return;
  const sel = t.notes.filter((n) => app.sel.has(n.id));
  if (!sel.length) {
    box.innerHTML = `<p class="muted">Select a note to edit its word, phonemes, vibrato and dynamics.</p><h3>Track</h3><div class="kv">
      <label>Expression</label><input id="i-expr" type="range" min="0" max="1" step="0.05">
      <label>Pitch centring</label><input id="i-corr" type="range" min="0" max="1" step="0.05">
      <label>Final steps</label><input id="i-steps" type="number" min="4" max="100"></div>
      <p class="muted">Expression 0 = flat robot, 1 = the voice's own style. Pitch centring 1 = every note centred on its pitch.</p>`;
    $('i-expr').value = t.params?.expr ?? 1; $('i-corr').value = t.params?.correct ?? 1; $('i-steps').value = t.params?.steps ?? 20;
    const setp = (k) => (e) => app.edit(k, (p) => { const x = app.trackOf(p); x.params = { ...(x.params || {}), [k]: Number(e.target.value) }; });
    $('i-expr').onchange = setp('expr'); $('i-corr').onchange = setp('correct'); $('i-steps').onchange = setp('steps');
    return;
  }
  const n = sel[0], many = sel.length > 1;
  box.innerHTML = `<div class="kv">
    <label>Word</label><input id="i-lyric">
    <label>Phonemes</label><input id="i-ph" placeholder="automatic">
    <label>Note</label><span id="i-note"></span>
    <label>Velocity</label><input id="i-vel" type="number" min="1" max="127">
    <label>Vibrato</label><input id="i-vd" type="number" min="0" max="200" step="5" title="extra depth, cents">
    <label>Vib. rate</label><input id="i-vr" type="number" min="3" max="9" step="0.1">
    <label>Vib. start</label><input id="i-vs" type="number" min="0" max="2000" step="10" title="ms after the note starts">
    <label>Lead-in</label><input id="i-lead" type="number" min="20" max="600" step="10" placeholder="auto" title="how early the consonants before the vowel start, ms">
    <label>Glide</label><input id="i-glide" type="number" min="10" max="1000" step="10" placeholder="auto" title="how long the slide from the previous note takes, ms">
    <label>Glide at</label><input id="i-goff" type="number" min="-500" max="500" step="10" title="where the slide is centred, ms after the note starts (negative = early)">
    </div><p><button id="i-retake" class="btn tiny" title="A new take of this phrase (R)">Retake phrase</button> <button id="i-take0" class="btn tiny">First take</button> <span id="i-take" class="muted"></span></p><p class="phones" id="i-auto"></p><div id="i-timing" class="timing"></div><p class="warn" id="i-warn"></p>${many ? `<p class="muted">${sel.length} notes selected: changes apply to all.</p>` : ''}`;
  $('i-lyric').value = many ? '' : n.lyric || ''; $('i-ph').value = n.phonemes || ''; $('i-note').textContent = `${NAMES[n.pitch % 12]}${Math.floor(n.pitch / 12) - 1} · ${(n.dur / PPQ).toFixed(2)} beats`;
  $('i-vel').value = n.vel ?? 64; $('i-vd').value = n.vib_depth ?? 0; $('i-vr').value = n.vib_rate ?? 5.5; $('i-vs').value = n.vib_start ?? 250;
  const setn = (k, conv = (v) => v) => (e) => app.edit(k, (p) => { for (const m of app.trackOf(p).notes) if (app.sel.has(m.id)) m[k] = conv(e.target.value); });
  $('i-lyric').onchange = setn('lyric', (v) => v.trim() || 'la'); $('i-ph').onchange = setn('phonemes', (v) => v.trim() || null);
  $('i-lead').value = n.lead ?? ''; $('i-lead').onchange = setn('lead', (v) => (v === '' ? null : Number(v)));
  $('i-glide').value = n.glide ?? ''; $('i-glide').onchange = setn('glide', (v) => (v === '' ? null : Number(v)));
  $('i-goff').value = n.glide_offset ?? 0; $('i-goff').onchange = setn('glide_offset', Number);
  const ph = phraseOf(n); $('i-take').textContent = ph ? `take ${ph.take + 1}` : '';
  $('i-retake').onclick = () => retake(n, +1); $('i-take0').onclick = () => retake(n, 0);
  $('i-vel').onchange = setn('vel', Number); $('i-vd').onchange = setn('vib_depth', Number); $('i-vr').onchange = setn('vib_rate', Number); $('i-vs').onchange = setn('vib_start', Number);
  if (app.syllableTrouble().has(n.id)) $('i-warn').textContent = 'This word has more syllables than notes: split it over more notes (sun- rise), or pick a shorter word.';
  if (!many) phonemeTiming(n);
  if (!many && n.lyric && !/^[_+.]$/.test(n.lyric)) post('/phonemize', { voice: app.track().voice, words: [n.lyric.replace(/-$/, '')] }).then((r) => r.json()).then((d) => { const ph = Object.values(d.phonemes || {})[0]; if (ph && $('i-auto')) $('i-auto').textContent = `automatic: ${ph.join(' ')}`; }).catch(() => {});
}

// ---- project lifecycle ----
function changed(label) {
  app.dirty = true; store.set('singer-autosave', { name: app.name, project: app.project() });
  if (!app.project().tracks.some((t) => t.id === app.trackId)) app.trackId = app.project().tracks[0].id;
  $('title').value = app.project().title || ''; $('bpm').value = app.project().tempo[0].bpm; $('ts').value = app.project().time_sig.join('/');
  const k = app.project().key; $('key-root').value = k ? String(k.root) : ''; $('key-scale').value = k?.scale || 'major';
  tracks(); tempoPane(); backing(); inspector(); draw();
  if (!['select'].includes(label) && !/backing/.test(label || '')) scheduleRender();
}
function open(project, name = null) {
  app.name = name; app.history.replace(project, 'open'); app.trackId = project.tracks[0]?.id; app.sel.clear(); app.renders = {};
  roll.centerOn(project.tracks.flatMap((t) => t.notes)); render('preview');
}
async function save() {
  const name = app.name || (app.project().title || 'Untitled').replace(/[^\w .()-]/g, '').slice(0, 80) || 'Untitled';
  const r = await post(`/projects/${encodeURIComponent(name)}`, app.project());
  if (r.ok) { app.name = name; app.dirty = false; status(`Saved as "${name}"`); } else status(`Save failed: ${(await r.json()).error}`);
}
async function openDialog() {
  const list = await (await fetch(`${API}/projects`)).json(), box = $('open-list'); box.textContent = '';
  if (!list.length) box.innerHTML = '<p class="muted">No saved projects yet.</p>';
  for (const p of list) {
    const row = document.createElement('div'); row.className = 'proj';
    row.innerHTML = `<span></span><span class="muted"></span>`; row.firstChild.textContent = p.name; row.lastChild.textContent = new Date(p.modified * 1000).toLocaleString();
    row.onclick = async () => { open(await (await fetch(`${API}/projects/${encodeURIComponent(p.name)}`)).json(), p.name); $('open-dlg').close(); };
    box.append(row);
  }
  // notes captured by the DAW plugin: into the track being edited (its words go back on with the lyrics line), or a new track
  const inbox = await (await fetch(`${API}/inbox`)).json(), ib = $('inbox-list'); ib.textContent = '';
  $('inbox-head').hidden = !inbox.length;
  for (const f of inbox) {
    const row = document.createElement('div'); row.className = 'proj';
    const name = document.createElement('span'); name.textContent = `${f.name} · ${new Date(f.modified * 1000).toLocaleString()}`;
    const into = document.createElement('button'); into.className = 'btn tiny'; into.textContent = 'Into this track';
    const add = document.createElement('button'); add.className = 'btn tiny'; add.textContent = 'As a new track';
    const take = async (asNew) => {
      const d = await (await fetch(`${API}/inbox/${encodeURIComponent(f.name)}`)).json();
      const ppq = app.project().ppq, scale = ppq / (d.ppq || 480);
      const notes = d.tracks.flatMap((t) => t.notes).map((n, i) => ({ ...n, id: `in${Date.now().toString(36)}${i}`, tick: Math.round(n.tick * scale), dur: Math.round(n.dur * scale), lyric: n.lyric || 'la' }));
      app.edit(asNew ? 'add DAW track' : 'notes from the DAW', (p) => {
        if (asNew) { const t = structuredClone(app.trackOf(p)); t.id = `t${Date.now().toString(36)}`; t.name = 'From DAW'; t.notes = notes; t.lanes = {}; t.pitch_draw = []; t.takes = {}; p.tracks.push(t); app.trackId = t.id; }
        else app.trackOf(p).notes = notes;
      });
      $('open-dlg').close(); status(`${notes.length} notes from ${f.name}: type the words in the lyrics line`);
    };
    into.onclick = () => take(false); add.onclick = () => take(true);
    row.append(name, into, add); ib.append(row);
  }
  $('open-dlg').showModal();
}
async function download(kind) {
  status(kind.startsWith('wav') ? 'Rendering the mix…' : 'Exporting…');
  const fmt = kind.startsWith('wav') ? 'wav' : kind;
  const r = await post('/export', { project: app.project(), format: fmt, track: kind === 'wav-track' ? app.track().id : null, bits: 24, include_backing: kind === 'wav-full' });
  if (!r.ok) { status(`Export failed: ${(await r.json()).error}`); return; }
  const blob = await r.blob(), a = document.createElement('a'), ext = { wav: 'wav', mid: 'mid', musicxml: 'musicxml', msing: 'msing' }[fmt];
  a.href = URL.createObjectURL(blob); a.download = `${app.project().title || 'song'}${kind === 'wav-track' ? ` - ${app.track().name}` : kind === 'wav-full' ? ' (with music)' : ''}.${ext}`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000); status(`Exported ${a.download}`);
}

// ---- wiring ----
async function init() {
  roll = new Roll($('roll'), app); lanes = new Lanes($('lanes'), app, roll);
  try { const v = await (await fetch(`${API}/voices`)).json(); app.voices = v.voices; app.modes = v.modes; } catch { app.modes = ['Default']; }
  for (const [k, s] of Object.entries(LANES)) $('lane').add(new Option(s.label, k, false, k === 'energy'));
  $('lane').onchange = (e) => { lanes.lane = e.target.value; lanes.draw(); };
  const saved = store.get('singer-autosave', null);
  app.history = new History(saved?.project || demo(), changed);
  app.name = saved?.name || null; app.trackId = app.project().tracks[0].id;
  changed('select'); roll.centerOn(app.project().tracks.flatMap((t) => t.notes)); render('preview');

  document.querySelectorAll('[data-tool]').forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
  // the bridge (design 12): offered when a voice converter is set up
  fetch(`${API}/bridge`).then((r) => r.json()).then((b) => { if (b.available) { $('bridge-opt').hidden = false; $('bridge-voice').textContent = (b.voice || '').split('/').pop(); } }).catch(() => {});
  $('bridge-close').onclick = () => $('bridge-dlg').close();
  $('bridge-go').onclick = async () => {
    $('bridge-go').disabled = true; $('bridge-out').hidden = true; $('bridge-state').textContent = 'Rendering…';
    const r = await post('/bridge', { project: app.project(), transpose: Number($('bridge-tr').value) || 0 });
    if (!r.ok) { $('bridge-state').textContent = (await r.json()).error; $('bridge-go').disabled = false; return; }
    const poll = async () => {
      const b = await (await fetch(`${API}/bridge`)).json();
      if (b.state === 'done') { $('bridge-state').textContent = 'Done'; $('bridge-audio').src = `${b.url}?t=${Date.now()}`; $('bridge-dl').href = b.url; $('bridge-out').hidden = false; $('bridge-go').disabled = false; return; }
      if (b.state === 'failed') { $('bridge-state').textContent = `Failed: ${b.error}`; $('bridge-go').disabled = false; return; }
      $('bridge-state').textContent = b.state === 'converting' ? `Converting into your voice… ${Math.round((Date.now() / 1000 - b.started))} s` : 'Rendering…';
      setTimeout(poll, 2000);
    };
    poll();
  };
  $('midi').onclick = toggleMidi; $('keys-close').onclick = () => $('keys-dlg').close(); $('group-done').onclick = leaveGroup;
  fetch(`${API}/scripts`).then((r) => r.json()).then((list) => { for (const sc of list) $('scripts').add(new Option(sc.kind === 'yours' ? `${sc.title} (yours)` : sc.title, sc.file)); }).catch(() => {});
  $('scripts').onchange = async (e) => {
    const f = e.target.value; e.target.value = ''; if (!f) return;
    try { const mod = await import(`${API}/scripts/${f}?v=${Date.now()}`); await mod.default(window.singer); status(`Ran "${mod.title || f}"`); }
    catch (err) { status(`Script failed: ${err.message}`); }
  };
  $('play').onclick = togglePlay; $('render').onclick = () => render('final'); $('check').onclick = check;
  $('save').onclick = save; $('open').onclick = openDialog; $('open-close').onclick = () => $('open-dlg').close();
  $('new').onclick = () => { open(newProject('Untitled', 120)); $('open-dlg').close(); };
  $('import').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return; status(`Importing ${f.name}…`);
    const r = await post(`/import?filename=${encodeURIComponent(f.name)}`, await f.arrayBuffer(), true);
    const d = await r.json(); if (!r.ok) { status(`Import failed: ${d.error}`); return; }
    open(d); status(`Imported ${f.name}: ${d.tracks.reduce((a, t) => a + t.notes.length, 0)} notes`); e.target.value = '';
  };
  $('export').onchange = (e) => { const k = e.target.value; e.target.value = ''; if (k === 'bridge') $('bridge-dlg').showModal(); else if (k) download(k); };
  $('title').onchange = (e) => app.edit('title', (p) => (p.title = e.target.value));
  $('key-root').add(new Option('none', '')); ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'].forEach((n, i) => $('key-root').add(new Option(n, String(i))));
  for (const sc of Object.keys(SCALES)) $('key-scale').add(new Option(sc, sc));
  const setKey = () => app.edit('key', (p) => { const r = $('key-root').value; if (r === '') delete p.key; else p.key = { root: Number(r), scale: $('key-scale').value }; });
  $('key-root').onchange = setKey; $('key-scale').onchange = setKey;
  $('bpm').onchange = (e) => app.edit('tempo', (p) => (p.tempo[0].bpm = Math.max(20, Math.min(300, Number(e.target.value) || 120))));
  $('ts').onchange = (e) => { const m = /^(\d+)\/(\d+)$/.exec(e.target.value.trim()); if (m) app.edit('time signature', (p) => (p.time_sig = [Number(m[1]), Number(m[2])])); };
  $('guide').onchange = (e) => (app.guide = e.target.checked);
  $('snap').onchange = () => draw();
  $('add-track').onclick = () => { const t = newTrack(`Track ${app.project().tracks.length + 1}`, app.track().voice); app.edit('add track', (p) => p.tracks.push(t)); app.trackId = t.id; changed('select'); };
  $('lyrics').onkeydown = (e) => { if (e.key === 'Enter') { applyLyrics(e.target.value); e.target.value = ''; } };
  document.addEventListener('keydown', keys);
}
function setTool(t) { app.tool = t; document.querySelectorAll('[data-tool]').forEach((b) => b.classList.toggle('on', b.dataset.tool === t)); }
function togglePlay() { if (player.playing) { player.stop(); $('play').textContent = 'Play'; } else { player.play(app.playTick); $('play').textContent = 'Stop'; } }
function applyLyrics(text) {
  const words = splitLyrics(text); if (!words.length) return;
  const ns = [...app.track().notes].sort((a, b) => a.tick - b.tick);
  const start = ns.findIndex((n) => app.sel.has(n.id)); const from = start < 0 ? 0 : start;
  const ids = ns.slice(from, from + words.length).map((n) => n.id);
  app.edit('lyrics', (p) => { const t = app.trackOf(p); ids.forEach((id, i) => { const n = t.notes.find((m) => m.id === id); if (n) n.lyric = words[i]; }); });
  app.sel.clear(); const next = ns[from + words.length]; if (next) app.sel.add(next.id);
  status(words.length > ids.length ? `${words.length - ids.length} word(s) had no note left` : `${ids.length} notes got their words`);
}
let clipboard = null;
// duplicate: a copy of the selection placed right after it (snapped to the bar when the selection is whole bars)
function duplicateSel() {
  const sel = app.track().notes.filter((n) => app.sel.has(n.id)); if (!sel.length) return;
  const lo = Math.min(...sel.map((n) => n.tick)), hi = Math.max(...sel.map((n) => n.tick + n.dur)), bar = ticksPerBar(app.project());
  const span = lo % bar === 0 && (hi - lo) % bar === 0 ? hi - lo : Math.ceil((hi - lo) / (app.snapTicks() || 1)) * (app.snapTicks() || 1);
  const copies = sel.map((n) => ({ ...n, id: uid(), tick: n.tick + span }));
  app.edit('duplicate', (p) => app.trackOf(p).notes.push(...copies)); app.sel = new Set(copies.map((n) => n.id)); changed('select');
}
// split: each selected note in two at the playhead (or in half); the second half holds the vowel ("_")
function splitSel() {
  const sel = app.track().notes.filter((n) => app.sel.has(n.id)); if (!sel.length) return;
  const made = [];
  app.edit('split notes', (p) => {
    const tr = app.trackOf(p);
    for (const n of tr.notes.filter((m) => app.sel.has(m.id))) {
      const at = app.playTick > n.tick + 10 && app.playTick < n.tick + n.dur - 10 ? Math.round(app.playTick) : n.tick + Math.round(n.dur / 2);
      const second = { ...n, id: uid(), tick: at, dur: n.tick + n.dur - at, lyric: '_', ph_scale: null }; n.dur = at - n.tick;
      tr.notes.push(second); made.push(second.id);
    }
  });
  app.sel = new Set([...app.sel, ...made]); changed('select'); status(`Split ${sel.length} note${sel.length > 1 ? 's' : ''}: the new halves hold the vowel (_)`);
}
// merge: the selected notes become one, from the first note's start to the last one's end, with the first's word and pitch
function mergeSel() {
  const sel = app.track().notes.filter((n) => app.sel.has(n.id)).sort((a, b) => a.tick - b.tick); if (sel.length < 2) return;
  const keep = sel[0].id, end = Math.max(...sel.map((n) => n.tick + n.dur));
  app.edit('merge notes', (p) => { const tr = app.trackOf(p); const k = tr.notes.find((n) => n.id === keep); k.dur = end - k.tick; tr.notes = tr.notes.filter((n) => n.id === keep || !app.sel.has(n.id)); });
  app.sel = new Set([keep]); changed('select');
}
function keys(e) {
  if (e.target.closest('input,select,textarea,dialog')) { if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); } return; }
  const mod = e.ctrlKey || e.metaKey, t = app.track();
  if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
  else if (mod && e.key === 'z') { e.preventDefault(); e.shiftKey ? app.history.redo() : app.history.undo(); }
  else if (mod && e.key === 'y') { e.preventDefault(); app.history.redo(); }
  else if (mod && e.key === 's') { e.preventDefault(); save(); }
  else if (mod && e.key === 'Enter') { e.preventDefault(); render('final'); }
  else if (mod && e.key === 'k') { e.preventDefault(); check(); }
  else if ((e.key === 'g' || e.key === 'G') && !mod) makeGroup();
  else if (e.key === 'Escape' && app.groupEdit) leaveGroup();
  else if ((e.key === 'r' || e.key === 'R') && !mod) { const n = t.notes.find((m) => app.sel.has(m.id)); if (n) retake(n, +1); }
  else if (mod && e.key === 'a') { e.preventDefault(); t.notes.forEach((n) => app.sel.add(n.id)); changed('select'); }
  else if (mod && e.key === 'c') { clipboard = t.notes.filter((n) => app.sel.has(n.id)).map((n) => ({ ...n })); }
  else if (mod && e.key === 'v' && clipboard?.length) {
    const lo = Math.min(...clipboard.map((n) => n.tick)), at = Math.round(app.playTick), copies = clipboard.map((n) => ({ ...n, id: uid(), tick: n.tick - lo + at }));
    app.edit('paste', (p) => app.trackOf(p).notes.push(...copies)); app.sel = new Set(copies.map((n) => n.id)); changed('select');
  }
  else if (mod && e.key === 'x') { clipboard = t.notes.filter((n) => app.sel.has(n.id)).map((n) => ({ ...n })); app.edit('cut', (p) => { const x = app.trackOf(p); x.notes = x.notes.filter((n) => !app.sel.has(n.id)); }); app.sel.clear(); }
  else if (mod && e.key === 'd') { e.preventDefault(); duplicateSel(); }
  else if (e.key === '/' && !mod) splitSel();
  else if (e.key === '?') $('keys-dlg').showModal();
  else if ((e.key === 'm' || e.key === 'M') && !mod) mergeSel();
  else if (e.key === 'Delete' || e.key === 'Backspace') { app.edit('delete notes', (p) => { const x = app.trackOf(p); x.notes = x.notes.filter((n) => !app.sel.has(n.id)); }); app.sel.clear(); }
  else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); const d = (e.key === 'ArrowUp' ? 1 : -1) * (e.shiftKey ? 12 : 1); app.edit('transpose notes', (p) => { for (const n of app.trackOf(p).notes) if (app.sel.has(n.id)) n.pitch += d; }); }
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); const d = (e.key === 'ArrowRight' ? 1 : -1) * (app.snapTicks() || PPQ / 4); app.edit('nudge notes', (p) => { for (const n of app.trackOf(p).notes) if (app.sel.has(n.id)) n.tick = Math.max(0, n.tick + d); }); }
  else if (e.key === 'q' || e.key === 'Q') { const s = app.snapTicks() || PPQ / 4; app.edit('quantize', (p) => { for (const n of app.trackOf(p).notes) if (app.sel.has(n.id)) { n.tick = Math.round(n.tick / s) * s; n.dur = Math.max(s, Math.round(n.dur / s) * s); } }); }
  else if (e.key === 'Home') { app.seek(0); roll.scrollTo(0); }
  else if (e.key === 'Escape') { app.sel.clear(); changed('select'); }
  else if ('vdpe'.includes(e.key.toLowerCase()) && !mod) setTool({ v: 'select', d: 'draw', p: 'pitch', e: 'erase' }[e.key.toLowerCase()]);
}

// the first project you see: the Chrome Sunrise hook, sung by the voice you have
function demo() {
  const p = newProject('Chrome Sunrise hook', 118);
  const tune = [[0, 240, 55, 'Ride'], [240, 240, 57, 'the'], [480, 480, 55, 'light,'], [960, 240, 58, 'feel'], [1200, 240, 60, 'the'], [1440, 480, 58, 'heat,'],
    [1920, 240, 62, 'chrome'], [2160, 240, 64, 'sun-'], [2400, 240, 62, 'rise'], [2640, 1200, 65, 'now']];
  p.tracks[0].notes = tune.map(([tick, dur, pitch, lyric]) => ({ id: uid(), tick, dur, pitch, lyric, vel: 64 }));
  return p;
}
// The scripting API (Synthesizer V has one; so do we): window.singer in the browser console or a script.
window.singer = {
  app, render, save, open, applyLyrics, togglePlay, check, retake, makeGroup, duplicateSel, splitSel, mergeSel, enterGroup, leaveGroup, midiNote: (pitch, vel = 90) => stepNote(pitch, app.snapTicks() || PPQ / 2, vel),
  project: () => app.project(), track: () => app.track(),
  edit: (label, fn) => app.edit(label, fn),
  select: (ids) => { app.sel = new Set(ids); app.changed('select'); },
  addNote: (tick, dur, pitch, lyric = 'la') => { const n = { id: uid(), tick, dur, pitch, lyric, vel: 64 }; app.edit('add note', (p) => app.trackOf(p).notes.push(n)); return n.id; },
  undo: () => app.history.undo(), redo: () => app.history.redo(),
};
init();
