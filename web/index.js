// Singer home: installed voices and the official downloads (the vocoder is needed before anything can sing).
const $ = (id) => document.getElementById(id);
const api = (p, opt = {}) => fetch(`/api/singer${p}`, { ...opt, headers: { 'content-type': 'application/json', 'x-mortiflix': '1' } });
let timer = null;

function row(cls, ...kids) { const d = document.createElement('div'); d.className = cls; d.append(...kids); return d; }
function text(tag, t, cls) { const e = document.createElement(tag); e.textContent = t; if (cls) e.className = cls; return e; }

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
  for (const v of mine) box.append(row('v-row', row('v-name', text('b', v.name), text('span', 'Your voice', 'muted')), text('span', 'Installed', 'ok')));
  const busy = dl.some((d) => d.state === 'downloading' || d.state === 'unpacking');
  clearTimeout(timer); if (busy) timer = setTimeout(refresh, 1000);
}
refresh();
