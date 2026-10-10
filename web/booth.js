// The Booth: sing each line of the script while a live tuner shows your pitch; every take is graded by the singer
// service. Tone-deaf first: the guide follows the key you start in, and the grade never depends on being in tune.
const API = '/api/singer';
const $ = (id) => document.getElementById(id);
const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const noteName = (m) => `${NAMES[((Math.round(m) % 12) + 12) % 12]}${Math.floor(Math.round(m) / 12) - 1}`;
const hz2midi = (f) => 69 + 12 * Math.log2(f / 440);
const midi2hz = (m) => 440 * 2 ** ((m - 69) / 12);
const store = { get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }, set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };

// ---- audio in: a worklet that tracks pitch (YIN) and hands over the raw samples ----


let ctx, mic, node, guideGain;
const listeners = new Set();
async function startAudio() {
  if (!window.isSecureContext || !navigator.mediaDevices) {     // browsers only open the microphone on secure pages
    throw new Error(`this page isn't secure, so the browser won't open the microphone. Open the Booth on this computer at http://localhost:4747/singer/booth.html (or in the desktop app)`);
  }
  ctx = new AudioContext();
  mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 } });
  await ctx.audioWorklet.addModule('tracker.worklet.js');
  node = new AudioWorkletNode(ctx, 'tracker');
  ctx.createMediaStreamSource(mic).connect(node);
  node.port.onmessage = (e) => listeners.forEach((f) => f(e.data));
  guideGain = ctx.createGain(); guideGain.gain.value = 0.18; guideGain.connect(ctx.destination);
}
const listen = (f) => { listeners.add(f); return () => listeners.delete(f); };

function collect(seconds) {            // raw samples + pitch frames for `seconds`
  return new Promise((ok) => {
    const pcm = [], frames = []; const t0 = ctx.currentTime;
    const off = listen((d) => {
      if (d.pcm) pcm.push(d.pcm); else frames.push(d);
      if (ctx.currentTime - t0 >= seconds) { off(); ok({ pcm, frames }); }
    });
  });
}
const db = (x) => 20 * Math.log10(Math.max(x, 1e-9));
const flat = (chunks) => { const n = chunks.reduce((a, c) => a + c.length, 0), out = new Float32Array(n); let o = 0; for (const c of chunks) { out.set(c, o); o += c.length; } return out; };

// ---- sounds: a soft guide tone, clicks, a drone ----
function tone(midi, at, dur, gain = 1) {
  const o = ctx.createOscillator(), o2 = ctx.createOscillator(), g = ctx.createGain();
  o.type = 'triangle'; o2.type = 'sine'; o.frequency.value = midi2hz(midi); o2.frequency.value = midi2hz(midi + 12);
  g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(0.9 * gain, at + 0.03); g.gain.setValueAtTime(0.9 * gain, at + Math.max(0.05, dur - 0.06)); g.gain.linearRampToValueAtTime(0, at + dur);
  const g2 = ctx.createGain(); g2.gain.value = 0.25; o2.connect(g2).connect(g);
  o.connect(g).connect(guideGain); o.start(at); o2.start(at); o.stop(at + dur + 0.05); o2.stop(at + dur + 0.05);
}
function click(at, strong) {
  const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.value = strong ? 1600 : 1100;
  g.gain.setValueAtTime(0.5, at); g.gain.exponentialRampToValueAtTime(0.001, at + 0.05);
  o.connect(g).connect(guideGain); o.start(at); o.stop(at + 0.06);
}
let droneNode = null;
function drone(midi) {
  if (droneNode) { droneNode.stop(); droneNode = null; }
  if (midi == null) return;
  const o = ctx.createOscillator(), g = ctx.createGain(); o.type = 'sine'; o.frequency.value = midi2hz(midi); g.gain.value = 0.35;
  o.connect(g).connect(guideGain); o.start(); droneNode = o;
}

// ---- setup checks ----
const setup = store.get('booth-setup', {});
$('mic').onclick = async () => {
  try { await startAudio(); $('mic-state').textContent = 'on'; ['room', 'level', 'range', 'start'].forEach((b) => ($(b).disabled = false)); }
  catch (e) { $('mic-state').textContent = `blocked: ${e.message} (the page needs https or localhost for the mic)`; }
};
$('room').onclick = async () => {
  $('room-state').textContent = 'listening…';
  const { frames } = await collect(5);
  const floor = db(frames.map((f) => f.rms).sort((a, b) => a - b)[Math.floor(frames.length / 2)] || 0);
  setup.noise = floor; store.set('booth-setup', setup);
  $('room-state').textContent = floor < -60 ? `quiet (${floor.toFixed(0)} dB): good` : floor < -50 ? `a little noise (${floor.toFixed(0)} dB): usable` : `noisy (${floor.toFixed(0)} dB): find the noise (fan, computer) or add blankets`;
};
$('level').onclick = async () => {
  $('level-state').textContent = 'sing "ah"…';
  const { pcm } = await collect(3);
  const peak = db(Math.max(...flat(pcm).map(Math.abs)));
  $('level-state').textContent = peak > -1 ? `clipping (${peak.toFixed(0)} dB): turn the input down` : peak < -24 ? `quiet (${peak.toFixed(0)} dB): turn the input up or move closer` : `good (${peak.toFixed(0)} dB)`;
};
$('range').onclick = async () => {
  $('range-state').textContent = 'slide low to high…';
  const { frames } = await collect(8);
  const m = frames.filter((f) => f.f0 > 0).map((f) => hz2midi(f.f0)).sort((a, b) => a - b);
  if (m.length < 10) { $('range-state').textContent = 'no singing heard, try again'; return; }
  const lo = m[Math.floor(m.length * 0.05)], hi = m[Math.floor(m.length * 0.95)];
  setup.range = [Math.round(lo), Math.round(hi)]; store.set('booth-setup', setup);
  $('range-state').textContent = `${noteName(lo)} to ${noteName(hi)}: the guides are moved into this range`;
};

// ---- the booth ----
let script = [], progress = null, line = null, lastTake = null, recording = false;
const rangeShift = (notes) => {         // whole octaves only, toward the singer's range centre
  if (!setup.range) return 0;
  const centre = (setup.range[0] + setup.range[1]) / 2, med = notes.map((n) => n.midi).sort((a, b) => a - b)[Math.floor(notes.length / 2)];
  return 12 * Math.round((centre - med) / 12);
};
// the four sit-down sessions (design 8b): held vowels and scales, then the balanced lines in two halves, then your
// songs, styles, holds and breaths. Any order works; this only shows where you are.
const cLines = () => script.filter((r) => r.set === 'C');
function sessionOf(l) {
  if (!l) return 1;
  if ('AB'.includes(l.set)) return 1;
  if (l.set === 'C') return cLines().findIndex((r) => r.id === l.id) < 150 ? 2 : 3;
  return 4;
}
function sessionText() {
  if (!progress) return;
  const sn = sessionOf(line), inS = script.filter((r) => sessionOf(r) === sn), keptS = inS.filter((r) => progress.kept[r.id]).length;
  $('session').textContent = `Session ${sn} of 4 · ${SESSION_NAMES[sn]} · ${keptS} of ${inS.length} kept`;
}
const SESSION_NAMES = { 1: 'Held vowels and scales', 2: 'Balanced lines, first half', 3: 'Balanced lines, second half', 4: 'Your songs, styles, holds and breaths' };
async function loadState() {
  const name = $('name').value.trim() || 'you';
  progress = await (await fetch(`${API}/booth/progress?name=${encodeURIComponent(name)}`)).json();
  const done = Object.keys(progress.kept).length;
  $('progress').textContent = `${done} of ${script.length} lines kept`;
  sessionText();
  finishLine(name, done);
}
// breaks: 2 minutes every 10 minutes of singing; and a tired voice (grades falling) suggests one sooner
const pace = { since: Date.now(), grades: [] };
function noteTake(grade) {
  pace.grades.push('ABC'.indexOf(grade));
  const recent = pace.grades.slice(-4), before = pace.grades.slice(0, -4);
  const avg = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  if (Date.now() - pace.since > 10 * 60 * 1000) banner('Ten minutes of singing: take a 2-minute break. Water, stretch, hum quietly.');
  else if (recent.length === 4 && before.length >= 4 && avg(recent) - avg(before) >= 0.75) banner('Your last takes got rougher, which is what a tired voice sounds like. Take a short break.');
}
function banner(text) { $('banner-text').textContent = text; $('banner').hidden = false; }
$('banner-ok').onclick = () => { $('banner').hidden = true; pace.since = Date.now(); pace.grades = []; };
// the finish line: enough kept to train (or everything kept) -> a summary and the way to Training
async function finishLine(name, done) {
  if (!$('finish').hidden) return;
  const st = await (await fetch(`${API}/train/status?name=${encodeURIComponent(name)}`)).json().catch(() => null);
  if (!st || (st.minutes < st.min_minutes && done < script.length)) return;
  const grades = Object.entries(progress.kept).map(([id, k]) => (progress.takes[id] || [])[k - 1]).filter(Boolean);
  const count = (g) => grades.filter((x) => x === g).length;
  $('finish').innerHTML = '';
  const h = document.createElement('b'); h.textContent = done >= script.length ? 'Every line is recorded.' : 'You have enough to build your voice.';
  const p = document.createElement('p'); p.className = 'muted';
  p.textContent = `${done} lines kept (${count('A')} A, ${count('B')} B) · ${st.minutes} minutes of singing. More lines make a better voice; you can keep going or build it now.`;
  const a = document.createElement('a'); a.className = 'btn primary'; a.href = 'training.html'; a.textContent = 'Build my voice';
  $('finish').append(h, p, a); $('finish').hidden = false;
}
function show(l) {
  line = l; lastTake = null;
  $('line-id').textContent = `Set ${l.set} · ${l.id}`;
  $('line-style').hidden = !l.style; $('line-style').textContent = l.style || '';
  $('line-text').textContent = l.text.trim();
  $('result').hidden = true; $('redo').disabled = true;
  trace.length = 0; drawRoll(0); sessionText();
}
function nextLine() {
  const kept = progress?.kept || {};
  const i = line ? script.findIndex((r) => r.id === line.id) : -1;
  const l = script.slice(i + 1).find((r) => !kept[r.id]) || script.find((r) => !kept[r.id]);
  if (l) show(l); else $('line-text').textContent = 'Every line is recorded. Build your voice from the Training page.';
}
$('start').onclick = async () => {
  script = await (await fetch(`${API}/script?name=${encodeURIComponent($('name').value.trim() || 'you')}`)).json();
  await loadState();
  $('setup').hidden = true; $('booth').hidden = false;
  const first = script.find((r) => r.id === progress.next) || script[0];
  show(first);
};

// live pitch for the needle and the trace
const trace = [];            // {t, midi}
let target = null, offset = 0, followLocked = false, takeStart = 0, downbeat = 0;
listen((d) => {
  if (!('f0' in d) || $('booth').hidden) return;
  $('meter-fill').style.width = `${Math.max(0, Math.min(100, (db(d.rms) + 60) / 60 * 100))}%`;
  if (!d.f0) { $('needle-words').textContent = recording ? '…' : 'sing a note'; return; }
  const m = hz2midi(d.f0);
  if (recording) trace.push({ t: ctx.currentTime - downbeat, midi: m });
  const ref = target != null ? target + offset : Math.round(m);
  const cents = Math.max(-100, Math.min(100, (m - ref) * 100));
  $('needle-note').textContent = noteName(m);
  $('needle-hand').style.transform = `rotate(${cents / 100 * 60}deg)`;
  const a = Math.abs(cents);
  $('needle-words').textContent = a <= 20 ? 'right on it' : cents < 0 ? (a <= 50 ? 'a little low, slide up' : 'low, slide up') : (a <= 50 ? 'a little high, slide down' : 'high, slide down');
  // follow me: the first steady sung note sets the key for the rest of the line
  if (recording && $('follow').checked && !followLocked && target != null) {
    const recent = trace.slice(-8);
    if (recent.length === 8 && Math.max(...recent.map((p) => p.midi)) - Math.min(...recent.map((p) => p.midi)) < 0.6) {
      offset = Math.round(recent.at(-1).midi - target); followLocked = true;
      if ($('drone').checked) drone(line.melody.notes[0].midi + rangeShift(line.melody.notes) + offset - 12);
    }
  }
});

// the guide roll: target bars (moved by the follow-me offset) and your pitch as a coloured line
function drawRoll(now) {
  const cv = $('roll'), g = cv.getContext('2d'); cv.width = cv.clientWidth * devicePixelRatio; cv.height = 240 * devicePixelRatio;
  g.scale(devicePixelRatio, devicePixelRatio);
  const W = cv.clientWidth, H = 240;
  if (!line) return;
  const shift = rangeShift(line.melody.notes), spb = 60 / line.melody.bpm;
  const ms = line.melody.notes.map((n) => n.midi + shift + offset);
  const lo = Math.min(...ms) - 5, hi = Math.max(...ms) + 5;
  const X = (t) => W / 3 + (t - now) * 90, Y = (m) => H - (m - lo) / (hi - lo) * H;
  const css = getComputedStyle(document.body);
  g.strokeStyle = css.getPropertyValue('--line'); g.lineWidth = 1;
  for (let m = Math.ceil(lo); m <= hi; m++) { g.beginPath(); g.moveTo(0, Y(m)); g.lineTo(W, Y(m)); g.stroke(); }
  g.fillStyle = css.getPropertyValue('--accent'); g.globalAlpha = 0.28;
  for (const n of line.melody.notes) { const m = n.midi + shift + offset; g.fillRect(X(n.beat * spb), Y(m) - 6, n.beats * spb * 90 - 3, 12); }
  g.globalAlpha = 1;
  for (let i = 1; i < trace.length; i++) {
    const p = trace[i], q = trace[i - 1]; if (p.t - q.t > 0.1) continue;
    const n = line.melody.notes.find((x) => p.t >= x.beat * spb && p.t < (x.beat + x.beats) * spb);
    const err = n ? Math.abs(p.midi - (n.midi + shift + offset)) * 100 : 0;
    g.strokeStyle = err <= 20 ? '#3ccf7d' : err <= 50 ? '#f5c518' : '#e5484d'; g.lineWidth = 3;
    g.beginPath(); g.moveTo(X(q.t), Y(q.midi)); g.lineTo(X(p.t), Y(p.midi)); g.stroke();
  }
  g.strokeStyle = css.getPropertyValue('--ink'); g.beginPath(); g.moveTo(W / 3, 0); g.lineTo(W / 3, H); g.stroke();
}

// ---- recording a take ----
function wav(samples, sr) {
  const b = new ArrayBuffer(44 + samples.length * 2), v = new DataView(b);
  const s = (o, str) => [...str].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  s(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); s(8, 'WAVE'); s(12, 'fmt '); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); s(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 32767, true);
  return new Blob([b], { type: 'audio/wav' });
}
async function record() {
  if (recording || !line) return;
  recording = true; $('rec').textContent = 'Recording… (Space to stop)';
  trace.length = 0; offset = 0; followLocked = !$('follow').checked; $('result').hidden = true;
  const notes = line.melody.notes, shift = rangeShift(notes), spb = 60 / line.melody.bpm;
  target = notes[0].midi + shift;
  const t0 = ctx.currentTime + 0.1;
  tone(target, t0, spb, 0.8);                                   // the reference note
  const count = 4; downbeat = t0 + spb * (1 + count);
  for (let i = 0; i < count; i++) click(t0 + spb * (1 + i), i === 0);
  if ($('drone').checked) drone(target - 12);
  const pcm = []; const off = listen((d) => { if (d.pcm && ctx.currentTime >= downbeat - 0.5) pcm.push(d.pcm); });
  const end = downbeat + notes.reduce((a, n) => Math.max(a, (n.beat + n.beats) * spb), 0) + 1.0;
  // schedule the guide a note at a time, so a follow-me offset found mid-line moves the rest of it
  let k = 0, stop = false;
  const tick = () => {
    if (stop) return;
    const now = ctx.currentTime;
    while (k < notes.length && downbeat + notes[k].beat * spb < now + 0.15) {
      const n = notes[k++];
      if ($('guide').checked) tone(n.midi + shift + offset, downbeat + n.beat * spb, n.beats * spb * 0.95, 0.6);
      target = n.midi + shift;
    }
    drawRoll(now - downbeat);
    if (now >= end) finish(); else requestAnimationFrame(tick);
  };
  const finish = async () => {
    if (stop) return; stop = true; off(); recording = false; drone(null);
    $('rec').textContent = 'Record (Space)'; $('rec').disabled = true;
    const y = flat(pcm);
    const name = $('name').value.trim() || 'you';
    $('result').hidden = false; $('result').className = 'result'; $('result').textContent = 'Checking the take…';
    try {
      const r = await (await fetch(`${API}/booth/take?name=${encodeURIComponent(name)}&id=${line.id}&preroll=0.5`, { method: 'POST', headers: { 'x-mortiflix': '1' }, body: wav(y, ctx.sampleRate) })).json();
      lastTake = r; noteTake(r.grade);
      $('result').className = `result ${r.grade}`;
      const why = r.grade === 'A' ? 'Kept. On to the next line.' : r.grade === 'B' ? 'Kept (it will be cleaned up later).' : 'One more try?';
      $('result').innerHTML = `<span class="grade">${r.grade}</span>${why}<br>${(r.problems || []).map((p) => `<span class="muted">${p}</span>`).join('<br>')}${r.key_offset ? `<br><span class="muted">You sang ${Math.abs(r.key_offset)} semitone${Math.abs(r.key_offset) === 1 ? '' : 's'} ${r.key_offset < 0 ? 'below' : 'above'} the guide. That's fine.</span>` : ''}`;
      $('redo').disabled = false;
      // hear it back; a C take can still be kept if you like it
      const row = document.createElement('div'); row.className = 'take-actions';
      const hear = document.createElement('button'); hear.className = 'btn'; hear.textContent = 'Hear it';
      const audio = document.createElement('audio'); audio.hidden = true; row.append(audio);
      hear.onclick = () => { audio.src = `${API}/booth/take.wav?name=${encodeURIComponent(name)}&id=${line.id}&take=${r.take}`; audio.play(); };
      row.append(hear);
      if (r.grade === 'C') {
        const keep = document.createElement('button'); keep.className = 'btn'; keep.textContent = 'Keep it anyway';
        keep.onclick = async () => {
          await fetch(`${API}/booth/keep?name=${encodeURIComponent(name)}&id=${line.id}&take=${r.take}`, { method: 'POST', headers: { 'x-mortiflix': '1' } });
          keep.disabled = true; keep.textContent = 'Kept'; await loadState();
        };
        row.append(keep);
      }
      $('result').append(row);
      await loadState();
    } catch (e) { $('result').textContent = `Couldn't check the take: ${e.message}`; }
    $('rec').disabled = false;
  };
  record.stop = finish;
  requestAnimationFrame(tick);
}
$('rec').onclick = () => (recording ? record.stop() : record());
$('redo').onclick = () => record();
$('next').onclick = () => nextLine();
$('drone').onchange = () => { if (!$('drone').checked) drone(null); };
document.addEventListener('keydown', (e) => {
  if ($('booth').hidden || e.target.tagName === 'INPUT') return;
  if (e.code === 'Space') { e.preventDefault(); recording ? record.stop() : record(); }
  else if (e.key === 'Enter') nextLine();
  else if (e.key === 'r' || e.key === 'R') record();
});
addEventListener('resize', () => drawRoll(0));

// set D: your song projects become Booth lines
fetch(`${API}/projects`).then((r) => r.json()).then((list) => {
  for (const p of list) $('song').add(new Option(p.name, p.name));
  $('song').onchange = () => { $('add-song').disabled = !$('song').value; };
}).catch(() => {});
$('add-song').onclick = async () => {
  const name = $('name').value.trim() || 'you';
  const r = await fetch(`${API}/booth/songs?name=${encodeURIComponent(name)}`, { method: 'POST', headers: { 'x-mortiflix': '1', 'content-type': 'application/json' }, body: JSON.stringify({ name: $('song').value }) });
  const d = await r.json();
  $('song-state').textContent = r.ok ? `${d.added} lines added from "${$('song').value}"` : d.error;
};
