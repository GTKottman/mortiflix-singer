// Training page: shows what's recorded, starts/stops the background job, follows its progress.
const $ = (id) => document.getElementById(id);
const api = (p, opt = {}) => fetch(`/api/singer${p}`, { ...opt, headers: { 'content-type': 'application/json', 'x-mortiflix': '1', ...(opt.headers || {}) } });
const STAGES = ['configs', 'binarize', 'acoustic', 'variance', 'export'];
const WORDS = { configs: 'Preparing', binarize: 'Reading your recordings', acoustic: 'Learning your sound', variance: 'Learning how you sing', export: 'Packing the voice' };
let timer = null;

async function refresh() {
  const name = $('name').value.trim() || 'you';
  const r = await api(`/train/status?name=${encodeURIComponent(name)}`); const s = await r.json();
  if (!r.ok) { $('advice').textContent = s.error; return; }
  $('minutes').textContent = `${s.minutes} min`; $('kept').textContent = `${s.kept} of ${s.lines}`;
  $('gpu').textContent = !s.installed ? 'not set up' : s.gpu ? 'graphics card (fast)' : 'processor only (slow)';
  const done = STAGES.filter((k) => s.state[k]).length, next = STAGES.find((k) => !s.state[k]);
  $('state').textContent = s.running ? `${WORDS[next] || 'Working'}${s.step ? ` · step ${s.step}` : ''}` : s.voice ? 'Voice ready' : s.exit ? 'Stopped with an error' : done ? 'Paused' : 'Not started';
  $('bar-fill').style.width = `${(done / STAGES.length) * 100}%`;
  const enough = s.minutes >= s.min_minutes;
  const kit = s.kit || {};
  $('kit').hidden = s.installed; $('kit').disabled = kit.state === 'installing';
  $('kit').textContent = kit.state === 'installing' ? `Installing: ${kit.step}…` : kit.state === 'failed' ? 'Try the install again' : 'Install the training kit (about 5 GB)';
  $('advice').textContent = !s.installed ? (kit.state === 'failed' ? `The training kit didn't install: ${kit.error}` : 'Training needs its kit once: Python, PyTorch and DiffSinger, downloaded and set up for you.')
    : s.busy_with && !s.running ? `Training "${s.busy_with}" now; one voice at a time.`
    : !enough ? `Record at least ${s.min_minutes} minutes (about an hour is better). You have ${s.minutes}.`
    : !s.gpu ? 'Without a graphics card this takes days. It works, just slowly.' : 'Ready. A full training takes several hours on a graphics card.';
  $('start').disabled = s.running || !s.installed || !enough || !!s.busy_with;
  $('start').textContent = done && !s.voice ? 'Continue training' : s.voice ? 'Train again' : 'Start training';
  $('stop').hidden = !s.running; $('use').hidden = !s.voice;
  $('log').hidden = !s.log; $('log').textContent = s.log;
  clearTimeout(timer); timer = setTimeout(refresh, s.running || kit.state === 'installing' ? 3000 : 15000);
}

$('start').onclick = async () => {
  const r = await api(`/train/start?name=${encodeURIComponent($('name').value.trim() || 'you')}`, { method: 'POST', body: JSON.stringify({ vocoder: $('vocoder').checked }) });
  if (!r.ok) $('advice').textContent = (await r.json()).error; refresh();
};
$('kit').onclick = async () => { await api('/train/kit', { method: 'POST', body: '{}' }); refresh(); };
$('stop').onclick = async () => { await api('/train/stop', { method: 'POST', body: '{}' }); refresh(); };
$('name').onchange = refresh;
refresh();
