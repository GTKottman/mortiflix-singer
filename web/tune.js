// Tune page: upload a vocal (+ its MIDI, or pick a key), correct it, see and hear before/after, download.
const $ = (id) => document.getElementById(id);
const api = (p, body, raw) => fetch(`/api/singer${p}`, { method: 'POST', headers: { 'x-mortiflix': '1', 'content-type': raw ? 'application/octet-stream' : 'application/json' }, body: raw ? body : JSON.stringify(body) });
const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const SCALES = ['major', 'minor', 'dorian', 'mixolydian', 'harmonic minor', 'pentatonic major', 'pentatonic minor', 'blues', 'chromatic'];
const st = { wav: null, notes: null, result: null };

$('root').add(new Option('—', '')); NAMES.forEach((n, i) => $('root').add(new Option(n, String(i))));
SCALES.forEach((s) => $('scale').add(new Option(s, s)));
const ready = () => { $('go').disabled = !(st.wav && (st.notes || $('root').value !== '')); };
const show = () => { $('amount-v').textContent = `${$('amount').value}%`; $('speed-v').textContent = `${$('speed').value} ms`; };
for (const id of ['amount', 'speed']) $(id).oninput = show;
$('root').onchange = ready;

$('wav').onchange = async () => {
  const f = $('wav').files[0]; if (!f) return; $('state').textContent = `Loading ${f.name}…`;
  const r = await api(`/tune/upload?filename=${encodeURIComponent(f.name)}`, await f.arrayBuffer(), true), d = await r.json();
  if (!r.ok) { $('state').textContent = d.error; return; }
  st.wav = d.file; $('wav-name').textContent = `${f.name} · ${d.duration} s`; $('state').textContent = ''; ready();
};
$('mid').onchange = async () => {
  const f = $('mid').files[0]; if (!f) return;
  const r = await api(`/tune/upload?filename=${encodeURIComponent(f.name)}`, await f.arrayBuffer(), true), d = await r.json();
  if (!r.ok) { $('state').textContent = d.error; return; }
  st.notes = d.notes; $('mid-name').textContent = `${f.name} · ${d.notes.length} notes`; ready();
};
$('go').onclick = async () => {
  $('go').disabled = true; $('state').textContent = 'Tuning…';
  const body = { wav: st.wav, amount: $('amount').value / 100, speed: Number($('speed').value), vibrato: $('vibrato').checked, offset_ms: Number($('offset').value) };
  if (st.notes) body.notes = st.notes; else body.key = { root: Number($('root').value), scale: $('scale').value };
  const r = await api('/tune', body), d = await r.json(); $('go').disabled = false;
  if (!r.ok) { $('state').textContent = `Failed: ${d.error}`; return; }
  st.result = d; $('state').textContent = 'Done'; draw();
  const rows = d.notes || [];
  if (rows.length) {
    const med = (a) => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
    const b = rows.map((x) => Math.abs(x.cents_before)), a = rows.map((x) => Math.abs(x.cents_after));
    $('summary').textContent = `${rows.length} notes: typically ${med(b)} cents off before, ${med(a)} after (worst ${Math.max(...b)} → ${Math.max(...a)}).`;
  } else $('summary').textContent = 'Every sung stretch moved onto the nearest note of the key.';
  $('ab').hidden = false; $('before').src = d.original; $('after').src = d.url; $('download').href = d.url; $('download').download = 'tuned.wav';
};

function draw() {
  const cv = $('curves'), d = st.result; cv.hidden = false;
  const W = cv.clientWidth, H = cv.height, dpr = devicePixelRatio || 1; cv.width = W * dpr; cv.style.height = `${H}px`;
  const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const css = getComputedStyle(document.body), c = (n) => css.getPropertyValue(n).trim();
  const pts = d.before.concat(d.after).filter((p) => p[1] != null), t1 = Math.max(...d.before.map((p) => p[0]));
  const ms = pts.map((p) => p[1]); let lo = Math.floor(Math.min(...ms)) - 1, hi = Math.ceil(Math.max(...ms)) + 1;
  if (hi - lo > 36) { const m = [...ms].sort((a, b) => a - b)[Math.floor(ms.length / 2)]; lo = Math.round(m - 18); hi = Math.round(m + 18); }
  const X = (t) => (t / t1) * W, Y = (m) => H - ((m - lo) / (hi - lo)) * H;
  g.fillStyle = c('--bg') || '#111'; g.fillRect(0, 0, W, H);
  g.strokeStyle = c('--line'); g.lineWidth = 0.5; for (let m = lo; m <= hi; m++) { g.globalAlpha = m % 12 === 0 ? 0.9 : 0.35; g.beginPath(); g.moveTo(0, Y(m)); g.lineTo(W, Y(m)); g.stroke(); } g.globalAlpha = 1;
  for (const n of d.notes || []) { g.fillStyle = c('--accent'); g.globalAlpha = 0.18; const m = n.midi + 12 * n.octave; g.fillRect(X(n.start), Y(m + 0.5), X(n.start + n.dur) - X(n.start), Y(m - 0.5) - Y(m + 0.5)); } g.globalAlpha = 1;
  const line = (arr, col, w) => { g.strokeStyle = col; g.lineWidth = w; g.beginPath(); let on = false; for (const [t, m] of arr) { if (m == null || m < lo - 2 || m > hi + 2) { on = false; continue; } on ? g.lineTo(X(t), Y(m)) : g.moveTo(X(t), Y(m)); on = true; } g.stroke(); };
  line(d.before, c('--muted'), 1); line(d.after, c('--accent'), 1.6);
}
show();
