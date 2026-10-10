// Mortiflix Singer editor: one screen (tracks, piano roll with words on notes, lanes, inspector), rendering through
// the singer service phrase by phrase while you edit.
import { History, newProject, newTrack, LANES, tempoMap, splitLyrics, syllables, uid, PPQ, SCALES, ticksPerBar, groupSpan, barAt, barToTick, tickToBar } from './model.js';
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
  onPlayhead(tick) {
    const lp = this.project().loop;                   // looping: past the loop's end, jump back to its start
    if (lp?.on && tick >= lp.end && player.playing) { this.seek(lp.start); return; }
    this.playTick = tick; draw();
  },
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
      if (syllables(word, t.lang) > group.length) group.forEach((n) => bad.add(n.id));
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
    draw(); if (app.sel.size === 1) inspector();      // the take lists follow the new render
  } catch (e) { status(`Render failed: ${e.message}`); }
}
function status(s) { $('status').textContent = s; }

// ---- retakes: a new random draw of the phrase a note is in (kept by number, so you can go back) ----
function phraseOf(n) { return (app.renders[app.track().id] || []).find((ph) => (ph.note_ids || []).includes(n.id)); }
function retake(n, how, kind = 'pitch') {
  // kind 'pitch': a new draw of the whole phrase; 'tone': the same pitch curve, a new draw of the voice.
  // how: +1 = a new take, or a take number to go back to (all takes stay cached, so going back is instant)
  const ph = phraseOf(n); if (!ph) { status('Render first, then retake'); return; }
  const ft = String(ph.first_tick), field = kind === 'tone' ? 'tone_takes' : 'takes';
  app.edit(kind === 'tone' ? 'tone take' : 'pitch take', (p) => {
    const t = app.trackOf(p); t[field] = t[field] || {}; t.take_max = t.take_max || {};
    const mx = t.take_max[ft] || { p: 0, q: 0 }, k = kind === 'tone' ? 'q' : 'p';
    const next = how === +1 ? mx[k] + 1 : how;
    t[field][ft] = next; mx[k] = Math.max(mx[k], next); t.take_max[ft] = mx;
    if (kind === 'pitch' && how === +1 && t.tone_takes) t.tone_takes[ft] = 0;      // a new pitch take starts from its own tone
  });
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
    const d = await (await post('/phonemize', { voice: app.track().voice, lang: app.track().lang || 'en', words: [w.text] })).json();
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
  const p = app.project(), t0 = barAt(p, Math.min(...sel.map((n) => n.tick))).start;   // groups start on a bar
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
  const p = app.project(), g = p.groups[x.r.group], uses = p.tracks.reduce((a, t) => a + (t.refs || []).filter((r) => r.group === g.id).length, 0);
  box.innerHTML = `<h3>Group</h3><div class="kv"><label>Name</label><input id="g-name"><label>At bar</label><input id="g-bar" type="number" min="1" step="0.25">
    <label>Transpose</label><input id="g-tr" type="number" step="1"></div><p class="muted" id="g-uses"></p>
    <p><button id="g-edit" class="btn tiny">Edit group</button> <button id="g-dup" class="btn tiny">Duplicate</button> <button id="g-un" class="btn tiny">Ungroup</button> <button id="g-del" class="btn tiny">Delete</button></p>`;
  $('g-name').value = g.name; $('g-bar').value = +tickToBar(p, x.r.tick).toFixed(2); $('g-tr').value = x.r.transpose || 0;
  $('g-uses').textContent = `${g.notes.length} notes · used ${uses} time${uses === 1 ? '' : 's'}`;
  const setR = (label, fn) => app.edit(label, (q) => { const r = q.tracks.flatMap((t) => t.refs || []).find((r) => r.id === app.selRef); if (r) fn(r, q); });
  $('g-name').onchange = (e) => app.edit('rename group', (q) => { q.groups[g.id].name = e.target.value || g.name; });
  $('g-bar').onchange = (e) => setR('move group', (r) => { r.tick = Math.max(0, barToTick(p, Number(e.target.value))); });
  $('g-tr').onchange = (e) => setR('transpose group', (r) => { r.transpose = Number(e.target.value) || 0; });
  $('g-dup').onclick = () => { const id = uid(); app.edit('duplicate group', (q) => { const tr = q.tracks.find((t) => (t.refs || []).some((r) => r.id === app.selRef)); const r = tr.refs.find((r) => r.id === app.selRef); const end = r.tick + groupSpan(g), b = barAt(q, end); tr.refs.push({ ...r, id, tick: b.start === end ? end : b.start + b.len }); }); app.selRef = id; changed('select'); };
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
    el.innerHTML = `<input class="name" value=""><div class="row"><select class="voice"></select><select class="mode"></select><select class="lang" title="the language the words are in"></select><label class="mstr-l" title="how strongly the vocal mode is applied">Strength <input class="mstr num" type="number" min="0" max="200" step="10">%</label></div>
      <div class="row"><span class="ms m" title="mute">M</span><span class="ms s" title="solo">S</span>
      <label title="volume in dB">dB <input class="gain num" type="number" step="0.5"></label>
      <label title="move the part by octaves (semitones)">Shift <input class="tr num" type="number" step="12"></label></div>`;
    el.querySelector('.name').value = t.name;
    const vs = el.querySelector('.voice'); for (const v of app.voices.length ? app.voices : [{ name: t.voice }]) vs.add(new Option(v.name, v.name, false, v.name === t.voice));
    const ms = el.querySelector('.mode'); for (const m of [...app.modes, ...Object.keys(p.modes || {})]) ms.add(new Option(m, m, false, m === t.mode));
    el.querySelector('.m').classList.toggle('on', !!t.mute); el.querySelector('.s').classList.toggle('on', !!t.solo);
    el.querySelector('.gain').value = t.gain_db || 0; el.querySelector('.tr').value = t.transpose || 0;
    const set = (label, k, v) => app.edit(label, (q) => { q.tracks.find((x) => x.id === t.id)[k] = v; });
    el.onclick = (e) => { if (e.target.closest('input,select,.ms')) return; app.trackId = t.id; app.sel.clear(); tracks(); draw(); inspector(); };
    el.querySelector('.name').onchange = (e) => set('rename track', 'name', e.target.value);
    vs.onchange = (e) => set('voice', 'voice', e.target.value);
    ms.onchange = (e) => set('vocal mode', 'mode', e.target.value);
    const lg = el.querySelector('.lang'); for (const [k, v] of Object.entries(app.langs || { en: 'English' })) lg.add(new Option(v, k, false, k === (t.lang || 'en')));
    lg.onchange = (e) => set('language', 'lang', e.target.value);
    const str = el.querySelector('.mstr'); str.value = Math.round((t.mode_strength ?? 1) * 100); el.querySelector('.mstr-l').hidden = (t.mode || 'Default') === 'Default';
    str.onchange = (e) => set('mode strength', 'mode_strength', Number(e.target.value) / 100);
    el.querySelector('.m').onclick = () => set('mute', 'mute', !t.mute);
    el.querySelector('.s').onclick = () => set('solo', 'solo', !t.solo);
    el.querySelector('.gain').onchange = (e) => set('volume', 'gain_db', Number(e.target.value));
    el.querySelector('.tr').onchange = (e) => set('octave', 'transpose', Number(e.target.value));
    box.append(el);
  }
}
function markersPane() {
  const p = app.project(), box = $('markers'); box.textContent = '';
  for (const m of [...(p.markers || [])].sort((a, b) => a.tick - b.tick)) {
    const row = document.createElement('div'); row.className = 'row';
    const go = document.createElement('button'); go.className = 'btn tiny'; go.textContent = `${+tickToBar(p, m.tick).toFixed(2)}`; go.title = 'jump here';
    go.onclick = () => { app.seek(m.tick); roll.scrollTo(Math.max(0, m.tick - p.ppq)); };
    const nm = document.createElement('input'); nm.value = m.name; nm.className = 'marker-name';
    nm.onchange = () => app.edit('rename marker', (q) => { const x = q.markers.find((y) => y.id === m.id); if (x) x.name = nm.value || x.name; });
    const rm = document.createElement('button'); rm.className = 'btn tiny'; rm.textContent = '×';
    rm.onclick = () => app.edit('remove marker', (q) => { q.markers = q.markers.filter((y) => y.id !== m.id); });
    row.append(go, nm, rm); box.append(row);
  }
  const add = document.createElement('button'); add.className = 'btn tiny'; add.textContent = 'Add at the playhead (;)';
  add.onclick = addMarker; box.append(add);
  if (p.loop) {
    const l = document.createElement('div'); l.className = 'row';
    const tg = document.createElement('button'); tg.className = 'btn tiny'; tg.textContent = p.loop.on ? 'Loop on (L)' : 'Loop off (L)';
    tg.onclick = toggleLoop; const rm = document.createElement('button'); rm.className = 'btn tiny'; rm.textContent = 'Clear loop';
    rm.onclick = () => app.edit('clear loop', (q) => { delete q.loop; });
    l.append(tg, rm); box.append(l);
  } else { const hint = document.createElement('p'); hint.className = 'muted'; hint.textContent = 'Shift-drag on the ruler to loop a part.'; box.append(hint); }
}
function addMarker() { const p = app.project(), tick = Math.round(app.playTick); app.edit('add marker', (q) => { q.markers = [...(q.markers || []), { id: uid(), tick, name: `Marker ${(p.markers || []).length + 1}` }]; }); }
function toggleLoop() { if (app.project().loop) app.edit('loop on/off', (q) => { q.loop.on = !q.loop.on; }); }
function tempoPane() {
  const p = app.project(), box = $('tempo'); box.textContent = '';
  const marks = [...p.tempo].sort((a, b) => a.tick - b.tick).filter((t) => t.tick > 0);
  for (const tp of marks) {
    const row = document.createElement('div'); row.className = 'row';
    const lab = document.createElement('span'); lab.textContent = `Bar ${+tickToBar(p, tp.tick).toFixed(2)}`;
    const bpm = document.createElement('input'); bpm.type = 'number'; bpm.className = 'num'; bpm.step = '0.1'; bpm.min = '20'; bpm.max = '300'; bpm.value = tp.bpm;
    bpm.onchange = () => app.edit('tempo change', (q) => { const m = q.tempo.find((x) => x.tick === tp.tick); if (m) m.bpm = Number(bpm.value) || m.bpm; });
    const rm = document.createElement('button'); rm.className = 'btn tiny'; rm.textContent = '×'; rm.title = 'remove this tempo change';
    rm.onclick = () => app.edit('remove tempo change', (q) => { q.tempo = q.tempo.filter((x) => x.tick !== tp.tick); });
    row.append(lab, bpm, document.createTextNode('BPM'), rm); box.append(row);
  }
  const add = document.createElement('div'); add.className = 'row';
  const at = document.createElement('input'); at.type = 'number'; at.className = 'num'; at.min = '2'; at.step = '1'; at.value = Math.max(2, barAt(p, app.playTick).index + 1); at.title = 'bar';
  const nb = document.createElement('input'); nb.type = 'number'; nb.className = 'num'; nb.step = '0.1'; nb.value = p.tempo[0].bpm; nb.title = 'BPM';
  const go = document.createElement('button'); go.className = 'btn tiny'; go.textContent = 'Add';
  go.onclick = () => { const tick = barToTick(p, Math.max(2, Number(at.value))); app.edit('tempo change', (q) => { q.tempo = q.tempo.filter((x) => x.tick !== tick); q.tempo.push({ tick, bpm: Number(nb.value) || q.tempo[0].bpm }); q.tempo.sort((a, b) => a.tick - b.tick); }); };
  add.append(document.createTextNode('At bar'), at, nb, go); box.append(add);
  // time-signature changes
  for (const m of [...(p.meters || [])].sort((a, b) => a.bar - b.bar)) {
    const row = document.createElement('div'); row.className = 'row';
    const lab = document.createElement('span'); lab.textContent = `Bar ${m.bar + 1}: ${m.num}/${m.den}`;
    const rm = document.createElement('button'); rm.className = 'btn tiny'; rm.textContent = '×'; rm.title = 'remove this time signature';
    rm.onclick = () => app.edit('remove time signature', (q) => { q.meters = q.meters.filter((x) => x.bar !== m.bar); });
    row.append(lab, rm); box.append(row);
  }
  const ms = document.createElement('div'); ms.className = 'row';
  const mb = document.createElement('input'); mb.type = 'number'; mb.className = 'num'; mb.min = '2'; mb.value = at.value; mb.title = 'bar';
  const mv = document.createElement('input'); mv.className = 'num'; mv.value = '3/4'; mv.title = 'time signature';
  const mg = document.createElement('button'); mg.className = 'btn tiny'; mg.textContent = 'Add';
  mg.onclick = () => { const r = /^(\d+)\/(\d+)$/.exec(mv.value.trim()), bar = Math.max(2, Number(mb.value)) - 1; if (!r) return;
    app.edit('time signature change', (q) => { q.meters = [...(q.meters || []).filter((x) => x.bar !== bar), { bar, num: Number(r[1]), den: Number(r[2]) }]; }); };
  ms.append(document.createTextNode('Meter at bar'), mb, mv, mg); box.append(ms);
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
// song-wide settings: export format, and your own vocal modes (offsets on the expression curves)
const MODE_KEYS = [['energy', 'Energy dB', 1], ['breathiness', 'Breath dB', 1], ['voicing', 'Voicing dB', 1], ['tension', 'Tension', 0.5], ['gender', 'Gender', 0.05]];
function songPanel(box) {
  const p = app.project(), ex = p.export || { rate: 44100, bits: 24 };
  const h = document.createElement('h3'); h.textContent = 'Song'; box.append(h);
  const kv = document.createElement('div'); kv.className = 'kv';
  kv.innerHTML = `<label>Export rate</label><select id="s-rate"><option value="44100">44.1 kHz</option><option value="48000">48 kHz</option></select>
    <label>Export depth</label><select id="s-bits"><option value="16">16-bit</option><option value="24">24-bit</option><option value="32">32-bit float</option></select>`;
  box.append(kv);
  $('s-rate').value = String(ex.rate); $('s-bits').value = String(ex.bits);
  $('s-rate').onchange = (e) => app.edit('export rate', (q) => { q.export = { ...(q.export || { bits: 24 }), rate: Number(e.target.value) }; });
  $('s-bits').onchange = (e) => app.edit('export depth', (q) => { q.export = { ...(q.export || { rate: 44100 }), bits: Number(e.target.value) }; });
  const mh = document.createElement('h3'); mh.textContent = 'Your vocal modes'; box.append(mh);
  for (const [name, m] of Object.entries(p.modes || {})) {
    const row = document.createElement('div'); row.className = 'mode-row';
    const nm = document.createElement('b'); nm.textContent = name; row.append(nm);
    for (const [k, label, step] of MODE_KEYS) {
      const l = document.createElement('label'); l.textContent = label;
      const inp = document.createElement('input'); inp.type = 'number'; inp.step = String(step); inp.value = m[k] ?? 0;
      inp.onchange = () => app.edit('vocal mode', (q) => { q.modes[name][k] = Number(inp.value) || 0; }); l.append(inp); row.append(l);
    }
    const rm = document.createElement('button'); rm.className = 'btn tiny'; rm.textContent = 'Remove';
    rm.onclick = () => app.edit('remove vocal mode', (q) => { delete q.modes[name]; for (const t of q.tracks) if (t.mode === name) t.mode = 'Default'; });
    row.append(rm); box.append(row);
  }
  const add = document.createElement('div'); add.className = 'row';
  const nm = document.createElement('input'); nm.placeholder = 'New mode name'; nm.className = 'mode-name';
  const go = document.createElement('button'); go.className = 'btn tiny'; go.textContent = 'Add mode';
  go.onclick = () => { const name = nm.value.trim(); if (!name || app.modes.includes(name)) return; app.edit('add vocal mode', (q) => { q.modes = { ...(q.modes || {}), [name]: { energy: 0, breathiness: 0, voicing: 0, tension: 0, gender: 0 } }; }); };
  add.append(nm, go); box.append(add);
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
    songPanel(box);
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
    <label>Scoop</label><input id="i-scoop" type="number" min="0" max="400" step="10" title="start this many cents below the note and rise into it">
    <label>Overshoot</label><input id="i-over" type="number" min="0" max="300" step="10" title="go this many cents past the note just after arriving">
    </div><div class="takes"><label>Pitch take</label><select id="i-ptake"></select><button id="i-retake" class="btn tiny" title="A new draw of the whole phrase (R)">New</button>
      <label>Tone take</label><select id="i-ttake"></select><button id="i-retone" class="btn tiny" title="The same pitch, a new draw of the voice (T)">New</button></div><p class="phones" id="i-auto"></p><div id="i-timing" class="timing"></div><p class="warn" id="i-warn"></p>${many ? `<p class="muted">${sel.length} notes selected: changes apply to all.</p>` : ''}`;
  $('i-lyric').value = many ? '' : n.lyric || ''; $('i-ph').value = n.phonemes || ''; $('i-note').textContent = `${NAMES[n.pitch % 12]}${Math.floor(n.pitch / 12) - 1} · ${(n.dur / PPQ).toFixed(2)} beats`;
  $('i-vel').value = n.vel ?? 64; $('i-vd').value = n.vib_depth ?? 0; $('i-vr').value = n.vib_rate ?? 5.5; $('i-vs').value = n.vib_start ?? 250;
  const setn = (k, conv = (v) => v) => (e) => app.edit(k, (p) => { for (const m of app.trackOf(p).notes) if (app.sel.has(m.id)) m[k] = conv(e.target.value); });
  $('i-lyric').onchange = setn('lyric', (v) => v.trim() || 'la'); $('i-ph').onchange = setn('phonemes', (v) => v.trim() || null);
  $('i-lead').value = n.lead ?? ''; $('i-lead').onchange = setn('lead', (v) => (v === '' ? null : Number(v)));
  $('i-glide').value = n.glide ?? ''; $('i-glide').onchange = setn('glide', (v) => (v === '' ? null : Number(v)));
  $('i-goff').value = n.glide_offset ?? 0; $('i-goff').onchange = setn('glide_offset', Number);
  $('i-scoop').value = n.scoop ?? 0; $('i-scoop').onchange = setn('scoop', Number);
  $('i-over').value = n.overshoot ?? 0; $('i-over').onchange = setn('overshoot', Number);
  const ph = phraseOf(n), mx = { ...(ph ? (t.take_max || {})[String(ph.first_tick)] || { p: 0, q: 0 } : { p: 0, q: 0 }) };
  if (ph) { mx.p = Math.max(mx.p, ph.take || 0); mx.q = Math.max(mx.q, ph.tone || 0); }   // projects from before take lists
  for (let k = 0; k <= mx.p; k++) $('i-ptake').add(new Option(String(k + 1), String(k), false, ph && ph.take === k));
  $('i-ttake').add(new Option('its own', '0', false, !ph?.tone)); for (let k = 1; k <= mx.q; k++) $('i-ttake').add(new Option(`tone ${k}`, String(k), false, ph?.tone === k));
  $('i-ptake').disabled = $('i-ttake').disabled = !ph;
  $('i-ptake').onchange = (e) => retake(n, Number(e.target.value), 'pitch'); $('i-ttake').onchange = (e) => retake(n, Number(e.target.value), 'tone');
  $('i-retake').onclick = () => retake(n, +1, 'pitch'); $('i-retone').onclick = () => retake(n, +1, 'tone');
  $('i-vel').onchange = setn('vel', Number); $('i-vd').onchange = setn('vib_depth', Number); $('i-vr').onchange = setn('vib_rate', Number); $('i-vs').onchange = setn('vib_start', Number);
  if (app.syllableTrouble().has(n.id)) $('i-warn').textContent = 'This word has more syllables than notes: split it over more notes (sun- rise), or pick a shorter word.';
  if (!many) phonemeTiming(n);
  if (!many && n.lyric && !/^[_+.]$/.test(n.lyric)) post('/phonemize', { voice: app.track().voice, lang: app.track().lang || 'en', words: [n.lyric.replace(/-$/, '')] }).then((r) => r.json()).then((d) => { const ph = Object.values(d.phonemes || {})[0]; if (ph && $('i-auto')) $('i-auto').textContent = `automatic: ${ph.join(' ')}`; }).catch(() => {});
}

// ---- project lifecycle ----
function changed(label) {
  app.dirty = true; store.set('singer-autosave', { name: app.name, project: app.project() });
  if (!app.project().tracks.some((t) => t.id === app.trackId)) app.trackId = app.project().tracks[0].id;
  $('title').value = app.project().title || ''; $('bpm').value = app.project().tempo[0].bpm; $('ts').value = app.project().time_sig.join('/');
  const k = app.project().key; $('key-root').value = k ? String(k.root) : ''; $('key-scale').value = k?.scale || 'major';
  tracks(); tempoPane(); markersPane(); backing(); inspector(); draw();
  if (!['select'].includes(label) && !/backing|marker|loop/.test(label || '')) scheduleRender();
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
  const ex = app.project().export || {};
  const r = await post('/export', { project: app.project(), format: fmt, track: kind === 'wav-track' ? app.track().id : null, bits: ex.bits || 24, sample_rate: ex.rate || 44100, include_backing: kind === 'wav-full' });
  if (!r.ok) { status(`Export failed: ${(await r.json()).error}`); return; }
  const blob = await r.blob(), a = document.createElement('a'), ext = { wav: 'wav', mid: 'mid', musicxml: 'musicxml', msing: 'msing' }[fmt];
  a.href = URL.createObjectURL(blob); a.download = `${app.project().title || 'song'}${kind === 'wav-track' ? ` - ${app.track().name}` : kind === 'wav-full' ? ' (with music)' : ''}.${ext}`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000); status(`Exported ${a.download}`);
}

// ---- wiring ----
async function init() {
  roll = new Roll($('roll'), app); lanes = new Lanes($('lanes'), app, roll);
  try { const v = await (await fetch(`${API}/voices`)).json(); app.voices = v.voices; app.modes = v.modes; app.langs = v.langs; } catch { app.modes = ['Default']; }
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
  const lo = Math.min(...sel.map((n) => n.tick)), hi = Math.max(...sel.map((n) => n.tick + n.dur)), b0 = barAt(app.project(), lo), b1 = barAt(app.project(), hi);
  const span = lo === b0.start && hi === b1.start ? hi - lo : Math.ceil((hi - lo) / (app.snapTicks() || 1)) * (app.snapTicks() || 1);
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
  if (e.target.closest?.('input,select,textarea,dialog')) { if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); } return; }
  const mod = e.ctrlKey || e.metaKey, t = app.track();
  if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
  else if (mod && e.key === 'z') { e.preventDefault(); e.shiftKey ? app.history.redo() : app.history.undo(); }
  else if (mod && e.key === 'y') { e.preventDefault(); app.history.redo(); }
  else if (mod && e.key === 's') { e.preventDefault(); save(); }
  else if (mod && e.key === 'Enter') { e.preventDefault(); render('final'); }
  else if (mod && e.key === 'k') { e.preventDefault(); check(); }
  else if ((e.key === 'g' || e.key === 'G') && !mod) makeGroup();
  else if (e.key === 'Escape' && app.groupEdit) leaveGroup();
  else if ((e.key === 'r' || e.key === 'R') && !mod) { const n = t.notes.find((m) => app.sel.has(m.id)); if (n) retake(n, +1, 'pitch'); }
  else if ((e.key === 't' || e.key === 'T') && !mod) { const n = t.notes.find((m) => app.sel.has(m.id)); if (n) retake(n, +1, 'tone'); }
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
  else if ((e.key === 'l' || e.key === 'L') && !mod) toggleLoop();
  else if (e.key === ';' && !mod) addMarker();
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
