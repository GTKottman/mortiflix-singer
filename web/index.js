// Singer home: installed voices and the official downloads (the vocoder is needed before anything can sing).
const $ = (id) => document.getElementById(id);
const api = (p, opt = {}) => fetch(`/api/singer${p}`, { ...opt, headers: { 'content-type': 'application/json', 'x-mortiflix': '1' } });
let timer = null;

function row(cls, ...kids) { const d = document.createElement('div'); d.className = cls; d.append(...kids); return d; }
function text(tag, t, cls) { const e = document.createElement(tag); e.textContent = t; if (cls) e.className = cls; return e; }

const post = (p, body) => fetch(`/api/singer${p}`, { method: 'POST', headers: { 'content-type': 'application/json', 'x-mortiflix': '1' }, body: JSON.stringify(body) });
// a voice's range drawn on two octaves of keys either side of it
function keyboard([lo, hi]) {
  const a = midiOf(lo), b = midiOf(hi), from = 12 * Math.floor((a - 12) / 12), to = 12 * Math.ceil((b + 12) / 12);
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'), whites = [];
  for (let m = from; m <= to; m++) if (![1, 3, 6, 8, 10].includes(m % 12)) whites.push(m);
  const W = 7; svg.setAttribute('viewBox', `0 0 ${whites.length * W} 26`); svg.setAttribute('class', 'kbd'); svg.setAttribute('aria-label', `range ${lo} to ${hi}`);
  whites.forEach((m, i) => { const r = document.createElementNS(ns, 'rect'); r.setAttribute('x', i * W); r.setAttribute('y', 0); r.setAttribute('width', W - 1); r.setAttribute('height', 26); r.setAttribute('class', m >= a && m <= b ? 'k in' : 'k'); svg.append(r); });
  whites.forEach((m, i) => { if ([0, 2, 5, 7, 9].includes(m % 12) && m + 1 <= to) { const r = document.createElementNS(ns, 'rect'); r.setAttribute('x', i * W + W * 0.65); r.setAttribute('y', 0); r.setAttribute('width', W * 0.7); r.setAttribute('height', 15); r.setAttribute('class', m + 1 >= a && m + 1 <= b ? 'kb in' : 'kb'); svg.append(r); } });
  const cap = document.createElement('span'); cap.className = 'muted'; cap.textContent = `${lo} to ${hi}`;
  const wrap = document.createElement('div'); wrap.className = 'range'; wrap.append(svg, cap); return wrap;
}
$('voice-zip').onchange = async () => {
  const f = $('voice-zip').files[0]; if (!f) return; $('voice-state').textContent = `Importing ${f.name}…`;
  const r = await fetch(`/api/singer/voices/import?filename=${encodeURIComponent(f.name)}`, { method: 'POST', headers: { 'x-mortiflix': '1' }, body: await f.arrayBuffer() });
  const d = await r.json(); $('voice-state').textContent = r.ok ? `Installed "${d.name}"` : d.error; refresh();
};

// a short phrase in a voice, placed in its range (or around middle C)
const NOTE = { C: 0, 'C#': 1, D: 2, 'D#': 3, E: 4, F: 5, 'F#': 6, G: 7, 'G#': 8, A: 9, 'A#': 10, B: 11 };
const midiOf = (n) => NOTE[n.slice(0, -1)] + 12 * (Number(n.slice(-1)) + 1);
function hear(v) {
  const b = text('button', 'Hear it', 'btn'), audio = document.createElement('audio'); audio.hidden = true; document.body.append(audio);
  b.onclick = async () => {
    b.disabled = true; b.textContent = 'Singing…';
    const mid = v.range ? Math.round((midiOf(v.range[0]) + midiOf(v.range[1])) / 2) : 60;
    const tune = [[0, 2, 'hel-'], [2, 2, 'lo'], [4, 1, 'this'], [5, 1, 'is'], [6, 1, 'my'], [7, 5, 'voice']];
    const steps = [0, 2, 4, 2, 0, -1];
    const project = { version: 1, ppq: 480, title: 'sample', tempo: [{ tick: 0, bpm: 100 }], time_sig: [4, 4],
      tracks: [{ id: 't1', name: 'Lead', voice: v.name, notes: tune.map(([at, len, w], i) => ({ id: `n${i}`, tick: at * 240, dur: len * 240 - 20, pitch: mid + steps[i], lyric: w, vel: 64 })), lanes: {}, pitch_draw: [], params: { steps: 10 } }] };
    try {
      const r = await fetch('/api/singer/export', { method: 'POST', headers: { 'content-type': 'application/json', 'x-mortiflix': '1' }, body: JSON.stringify({ project, format: 'wav', bits: 16 }) });
      if (!r.ok) throw new Error((await r.json()).error);
      audio.src = URL.createObjectURL(await r.blob()); await audio.play();
    } catch (e) { b.title = e.message; }
    b.disabled = false; b.textContent = 'Hear it';
  };
  return b;
}

async function refresh() {
  const [dl, vs] = await Promise.all([api('/downloads').then((r) => r.json()), api('/voices').then((r) => r.json())]);
  const box = $('voices'); box.textContent = '';
  for (const d of dl) {
    const right = document.createElement('span');
    if (d.state === 'downloading' || d.state === 'unpacking') right.append(text('span', d.state === 'unpacking' ? 'Unpacking…' : `${d.done_mb} of ${d.total_mb || d.size_mb} MB`, 'muted'));
    else if (d.installed) right.append(text('span', 'Installed', 'ok'));
    else {
      const b = text('button', `Download (${d.size_mb} MB)`, `btn${d.required ? ' primary' : ''}`);
      b.onclick = async () => { await api(`/downloads/start?id=${d.id}`, { method: 'POST', body: '{}' }); refresh(); };
      right.append(b);
      if (d.state === 'failed') right.append(text('span', ` Failed: ${d.error}`, 'bad'));
    }
    const left = row('v-name', text('b', d.title), text('span', `${d.required ? 'Needed to sing. ' : ''}${d.license}`, 'muted'));
    if (d.terms) { const a = text('a', 'Terms of use'); a.href = d.terms; a.target = '_blank'; a.rel = 'noopener'; left.append(a); }
    box.append(row('v-row', left, right));
  }
  const mine = vs.voices.filter((v) => !dl.some((d) => d.id === v.name));
  for (const v of mine) {
    const left = row('v-name', text('b', v.name), text('span', v.license || 'Your voice', 'muted'));
    if (v.range) left.append(keyboard(v.range));
    const right = row('v-actions', hear(v));
    if (vs.default === v.name) right.append(text('span', 'Default', 'ok'));
    else { const d = text('button', 'Make default', 'btn'); d.onclick = async () => { await post('/voices/default', { name: v.name }); refresh(); }; right.append(d); }
    if (v.removable) {
      const del = text('button', 'Delete', 'btn');
      del.onclick = async () => {                     // two clicks, no pop-up: the first arms it
        if (del.dataset.armed !== '1') { del.dataset.armed = '1'; del.textContent = 'Delete it for good?'; return; }
        await post('/voices/delete', { name: v.name }); refresh();
      };
      right.append(del);
    }
    box.append(row('v-row', left, right));
  }
  for (const v of vs.voices.filter((x) => dl.some((d) => d.id === x.name))) {         // downloaded voices can be heard too
    const r = [...box.children].find((el) => el.querySelector('b')?.textContent.startsWith(v.name)); if (!r) continue;
    r.lastChild.prepend(hear(v), ' ');
    if (v.range) r.firstChild.append(keyboard(v.range));
    if (vs.default === v.name) r.lastChild.append(' ', text('span', 'Default', 'ok'));
    else { const d = text('button', 'Make default', 'btn'); d.onclick = async () => { await post('/voices/default', { name: v.name }); refresh(); }; r.lastChild.append(' ', d); }
  }
  const busy = dl.some((d) => d.state === 'downloading' || d.state === 'unpacking');
  clearTimeout(timer); if (busy) timer = setTimeout(refresh, 1000);
}
refresh();

// saved projects, newest first: one click opens them in the editor
fetch('/api/singer/projects').then((r) => r.json()).then((list) => {
  const box = $('projects'); box.textContent = '';
  if (!list.length) { box.append(text('p', 'None yet: the Editor saves them here.', 'muted')); return; }
  for (const p of list.slice(0, 12)) {
    const a = text('a', p.name); a.href = `editor.html?project=${encodeURIComponent(p.name)}`;
    box.append(row('v-row', row('v-name', a), text('span', new Date(p.modified * 1000).toLocaleString(), 'muted')));
  }
}).catch(() => {});
