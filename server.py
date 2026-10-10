#!/usr/bin/env python3
"""The singer service: the Booth's script, takes and grades (and later rendering), over a UNIX socket so no TCP port
is opened. Mortiflix Music forwards /api/singer/* to it and serves the web pages at /singer/.

  server.py [--socket ~/MortiflixSinger/singer.sock] [--home ~/MortiflixSinger]
"""
import argparse, io, json, os, re, socketserver, sys, threading, time, warnings
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import numpy as np, soundfile as sf

warnings.filterwarnings('ignore')
HERE = Path(__file__).parent
if getattr(sys, 'frozen', False):          # the desktop app's bundled service: data files unpacked next to it
    os.environ.setdefault('NLTK_DATA', str(Path(sys._MEIPASS) / 'nltk_data'))
sys.path.insert(0, str(HERE))
from booth.grade import grade
from engine import formats
from engine.project import render_track, mixdown, MODES, expand_groups
from engine.song import phonemes as phonemize

SCRIPT = json.loads((HERE / 'booth/script.json').read_text())
LINES = {r['id']: r for r in SCRIPT}
ID = re.compile(r'^[A-Z]\d{4}$')
NAME = re.compile(r'^[a-z0-9_-]{1,40}$')
lock = threading.Lock()


class Store:
    def __init__(self, home: Path):
        self.home = home
        self.voices_cache, self.render_lock = {}, threading.Lock()

    # ---- voices (the rules live in engine/voices.py, shared with the CLI and the MCP) ----
    def voice_dirs(self):
        from engine import voices
        return voices.voice_dirs(self.home)

    def vocoder_dir(self, voice_dir):
        from engine import voices
        return voices.vocoder_dir(voice_dir, self.home)

    def voice(self, name):
        from engine.ds import Voice
        if name not in self.voices_cache:
            dirs = self.voice_dirs()
            if name not in dirs: raise ValueError(f'no voice "{name}" (installed: {", ".join(dirs) or "none"})')
            self.voices_cache[name] = Voice(dirs[name], self.vocoder_dir(dirs[name]))
        return self.voices_cache[name]

    def voices(self):
        from engine import voices
        return [{'name': name, **voices.info(d), 'image': (d / 'icon.png').exists()} for name, d in self.voice_dirs().items()]

    # ---- projects ----
    def projects_dir(self):
        d = self.home / 'projects'; d.mkdir(parents=True, exist_ok=True); return d

    def project_file(self, name):
        if not re.match(r'^[\w .()-]{1,80}$', name): raise ValueError('bad project name')
        return self.projects_dir() / f'{name}.msing'

    def write_mix(self, name, project, phrases_by_track):
        """<project>.mix.json beside the project: what the DAW plugin plays (rendered phrases, track gain/pan/mute/solo,
        the tempo map so it can follow the host's beat position)."""
        f = self.project_file(name).with_suffix('.mix.json')
        mix = {'version': 1, 'project': name, 'ppq': project.get('ppq', 480), 'tempo': project.get('tempo'), 'sample_rate': 44100,
               'updated': time.time(),
               'tracks': [{'id': t['id'], 'name': t.get('name', ''), 'gain_db': t.get('gain_db', 0), 'pan': t.get('pan', 0),
                           'mute': bool(t.get('mute')), 'solo': bool(t.get('solo')), 'phrases': phrases_by_track.get(t['id'], [])}
                          for t in project['tracks']]}
        tmp = f.with_suffix('.tmp'); tmp.write_text(json.dumps(mix)); tmp.replace(f)

    def dataset(self, name):
        if not NAME.match(name): raise ValueError('bad voice name')
        d = self.home / 'datasets' / name
        (d / 'raw').mkdir(parents=True, exist_ok=True)
        return d

    def booth(self, name):
        f = self.dataset(name) / 'booth.json'
        return json.loads(f.read_text()) if f.exists() else {'takes': {}, 'kept': {}}

    def save_booth(self, name, b):
        f = self.dataset(name) / 'booth.json'
        tmp = f.with_suffix('.tmp'); tmp.write_text(json.dumps(b, indent=1)); tmp.replace(f)

    def script(self, name):
        """The Booth's lines for this singer: the fixed script plus set D, lines from their own songs."""
        f = self.dataset(name) / 'songs.json'
        return SCRIPT + (json.loads(f.read_text()) if f.exists() else [])

    def line(self, name, lid):
        return LINES.get(lid) or next((r for r in self.script(name) if r['id'] == lid), None)

    def add_song(self, name, project):
        """Each sung phrase of a project becomes a Booth line (set D) with its words and melody."""
        from engine.project import expand_groups, TempoMap
        from engine.song import words_of, phrases_of
        p = expand_groups(project); f = self.dataset(name) / 'songs.json'
        have = json.loads(f.read_text()) if f.exists() else []
        n0 = max([int(r['id'][1:]) for r in have] or [900]) + 1
        tm = TempoMap(p); bpm = p['tempo'][0]['bpm']; spb = 60000 / bpm; added = []
        for t in p['tracks']:
            notes = sorted(t['notes'], key=lambda n: n['tick'])
            raw = [[tm.to_ms(n['tick']), tm.to_ms(n['tick'] + n['dur']) - tm.to_ms(n['tick']), n['pitch']] for n in notes]
            toks = [(n.get('lyric') or 'la') for n in notes]
            for ph in phrases_of(words_of(raw, toks, {}, t.get('lang', 'en'))):
                ns = [n for w in ph for n in w.notes]
                text = ' '.join(re.sub(r'\{.*?\}', '', getattr(w, 'text', '') or '').strip() for w in ph).strip()
                text = re.sub(r'\s+', ' ', re.sub(r'[^\w\s\',.!?-]', '', text))
                if not text or len(ns) < 2: continue
                s0 = ns[0].start
                added.append({'set': 'D', 'id': f'D{n0 + len(added):04d}', 'text': text, 'song': p.get('title', ''), 'syllables': len(ns),
                              'melody': {'bpm': bpm, 'notes': [{'beat': round((n.start - s0) / spb, 3), 'beats': round(n.dur / spb, 3), 'midi': int(round(n.midi))} for n in ns]}})
        tmp = f.with_suffix('.tmp'); tmp.write_text(json.dumps(have + added, indent=1)); tmp.replace(f)
        return added

    def progress(self, name):
        b = self.booth(name)
        sets = {}
        for r in self.script(name):
            s = sets.setdefault(r['set'], {'lines': 0, 'kept': 0})
            s['lines'] += 1; s['kept'] += r['id'] in b['kept']
        nxt = next((r['id'] for r in self.script(name) if r['id'] not in b['kept']), None)
        return {'sets': sets, 'next': nxt, 'kept': b['kept'], 'takes': {k: [t['grade'] for t in v] for k, v in b['takes'].items()}}


DOWNLOADS = {   # official releases only, fetched on the user's request; never bundled (their licenses are not ours)
    'vocoder': {'title': 'NSF-HiFiGAN vocoder (OpenVPI), for SPORE', 'required': True, 'size_mb': 53,
                'url': 'https://github.com/openvpi/vocoders/releases/download/nsf-hifigan-44.1k-hop512-128bin-2024.02/nsf_hifigan_44.1k_hop512_128bin_2024.02.oudep',
                'dest': 'nsf_hifigan', 'license': 'CC BY-NC-SA 4.0: non-commercial use only'},
    'bigvgan': {'title': 'BigVGAN v2 vocoder (NVIDIA), for voices you train', 'required': False, 'size_mb': 455,
                'url': 'https://github.com/GTKottman/mortiflix-singer/releases/download/vocoder-bigvgan-v2/bigvgan_v2.zip',
                'dest': 'bigvgan_v2', 'license': 'MIT: commercial use allowed'},
    'SPORE': {'title': 'SPORE, an English voice by Knoxstation', 'required': False, 'size_mb': 300,
              'url': 'https://github.com/knoxstation/SPORE/releases/download/v.0.1.1/SPORE011.zip',
              'dest': 'SPORE', 'license': 'CC BY-NC-ND 4.0: non-commercial use only, credit Knoxstation',
              'terms': 'https://github.com/knoxstation/SPORE/blob/main/TOS.md'},
}


class Downloads:
    """Voice and vocoder downloads, one thread each, progress kept in memory."""
    def __init__(self, store):
        self.store, self.jobs = store, {}

    def installed(self, key):
        from engine import voices
        dest = DOWNLOADS[key]['dest']
        if key in ('vocoder', 'bigvgan'):        # anywhere the engine looks (your voices folder or the checkout's)
            return any((base / dest / 'vocoder.yaml').exists() for base in voices.homes(self.store.home))
        return key in voices.voice_dirs(self.store.home)

    def status(self):
        return [{'id': k, **{x: v[x] for x in ('title', 'required', 'size_mb', 'license')}, 'terms': v.get('terms'),
                 'installed': self.installed(k), **self.jobs.get(k, {})} for k, v in DOWNLOADS.items()]

    def start(self, key):
        import urllib.request, zipfile, shutil, tempfile
        if key not in DOWNLOADS: raise ValueError('unknown download')
        if self.jobs.get(key, {}).get('state') == 'downloading': return {'started': False}
        info = DOWNLOADS[key]; job = self.jobs[key] = {'state': 'downloading', 'done_mb': 0.0}

        def run():
            try:
                fd, name = tempfile.mkstemp(suffix='.zip', dir=self.store.home); os.close(fd)   # Windows can't delete an open file
                tmp = Path(name)
                with urllib.request.urlopen(info['url'], timeout=60) as r, open(tmp, 'wb') as f:
                    total = int(r.headers.get('content-length') or 0); job['total_mb'] = round(total / 1e6, 1)
                    while (chunk := r.read(1 << 20)):
                        f.write(chunk); job['done_mb'] = round(f.tell() / 1e6, 1)
                job['state'] = 'unpacking'
                dest = self.store.home / 'voices' / info['dest']
                if dest.exists(): shutil.rmtree(dest)
                with zipfile.ZipFile(tmp) as z:
                    for m in z.namelist():                       # nothing may land outside the voice folder
                        if m.startswith('/') or '..' in Path(m).parts: raise ValueError(f'unsafe path in the download: {m}')
                    z.extractall(dest)
                tmp.unlink()
                if key in ('vocoder', 'bigvgan'):                # the engine wants vocoder.yaml at the folder's top
                    y = next(dest.rglob('vocoder.yaml')).parent
                    if y != dest:
                        for f in y.iterdir(): shutil.move(str(f), dest / f.name)
                job['state'] = 'installed'
            except Exception as e:
                job.update(state='failed', error=str(e) or type(e).__name__)
        threading.Thread(target=run, daemon=True).start()
        return {'started': True}


class Bridge:
    """Design section 12: the project rendered by the engine, then converted into your voice by a speech-to-speech
    command (robovox's s2s.py with SoulX-Singer SVC) using a recording of you as the reference. Configured in
    ~/MortiflixSinger/config.json {"bridge": {"command": "...", "voice": "..."}}; found automatically when robovox is
    checked out next to this project. One job at a time, in the background."""
    def __init__(self, store):
        self.store, self.job = store, None

    def config(self):
        f = self.store.home / 'config.json'
        cfg = (json.loads(f.read_text()).get('bridge') if f.exists() else None) or {}
        rv = HERE.parent / 'robovox'
        if not cfg.get('command') and (rv / 's2s.py').exists() and (rv / '.venv/bin/python').exists():
            cfg = {'command': f'{rv / ".venv/bin/python"} {rv / "s2s.py"}', 'voice': str(rv / 'voices' / ('you-better' if (rv / 'voices/you-better').exists() else 'you'))}
        return cfg if cfg.get('command') and cfg.get('voice') else None

    def status(self):
        j = self.job
        return {'available': self.config() is not None, 'voice': (self.config() or {}).get('voice'),
                **({k: j[k] for k in ('state', 'error', 'url', 'started')} if j else {'state': None})}

    def start(self, project, transpose):
        import shlex, subprocess, hashlib
        if self.job and self.job['state'] in ('rendering', 'converting'): raise ValueError('a conversion is already running')
        cfg = self.config()
        if not cfg: raise ValueError('no voice converter set up (robovox s2s.py)')
        key = hashlib.sha1(json.dumps([project, transpose, cfg], sort_keys=True).encode()).hexdigest()[:16]
        d = self.store.home / 'bridge' / key; d.mkdir(parents=True, exist_ok=True)
        self.job = job = {'state': 'rendering', 'error': None, 'url': None, 'started': time.time()}

        def run():
            try:
                p = expand_groups(project); results, sr = {}, 44100
                with self.store.render_lock:
                    for t in p['tracks']:
                        if not t['notes']: continue
                        v = self.store.voice(t.get('voice') or 'SPORE'); sr = v.sr
                        results[t['id']] = render_track(v, t.get('voice') or 'SPORE', p, t, self.store.home / 'cache', 'final')
                mix = mixdown(sr, p, results, p['tracks']).mean(1)
                sf.write(d / 'source.wav', mix, sr, subtype='PCM_24')
                (d / 'part.mid').write_bytes(formats.to_midi(p))
                job['state'] = 'converting'
                cmd = shlex.split(cfg['command']) + ['--source', str(d / 'source.wav'), '--voice', cfg['voice'], '--out', str(d),
                                                     '--midi', str(d / 'part.mid'), '--transpose', str(int(transpose))]
                with open(d / 'log.txt', 'w') as log:
                    r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
                if r.returncode or not (d / 'vocal.wav').exists(): raise RuntimeError(f'the converter failed: see {d / "log.txt"}')
                job.update(state='done', url=f'/api/singer/bridge/{key}.wav')
            except Exception as e:
                job.update(state='failed', error=str(e))
        threading.Thread(target=run, daemon=True).start()
        return {'started': True}


MIN_MINUTES = 30        # below this a voice is too thin to be worth hours of training (DiffSinger asks for about an hour)
VENV_PY = ('Scripts', 'python.exe') if os.name == 'nt' else ('bin', 'python')
# the training sources: the checkout in development, the copy bundled inside the desktop app otherwise
SOURCES = Path(sys._MEIPASS) / 'sources' if getattr(sys, 'frozen', False) else HERE


class Trainer:
    """One training job at a time, in the background: Booth takes -> dataset -> DiffSinger -> a voice in voices/.
    The job runs as its own process (PID kept, stopped by PID only) so the service stays free to render. The trainer
    runs from the checkout's trainer/ when it is set up (trainer/setup.sh), otherwise from the training kit that the
    app installs on request (trainer/kit.py)."""
    def __init__(self, store):
        self.store, self.proc, self.name, self.gpu = store, None, None, None
        self.kit_job = {'state': None}

    def env(self):
        """-> (python, trainer folder) or (None, None) when nothing is installed yet."""
        dev = HERE / 'trainer'
        if (dev / '.venv').joinpath(*VENV_PY).exists() and (HERE / 'ref' / 'DiffSinger').exists(): return dev / '.venv' / VENV_PY[0] / VENV_PY[1], dev
        sys.path.insert(0, str(SOURCES / 'trainer'))
        import kit
        if kit.ready(self.store.home): return kit.python_of(self.store.home), kit.kit_dir(self.store.home) / 'trainer'
        return None, None

    def install_kit(self):
        if self.kit_job.get('state') == 'installing': return {'started': False}
        sys.path.insert(0, str(SOURCES / 'trainer'))
        import kit
        job = self.kit_job = {'state': 'installing', 'step': 'Starting', 'error': None}

        def run():
            try:
                kit.install(self.store.home, SOURCES, progress=lambda m: job.update(step=m)); job['state'] = 'done'; self.gpu = None
            except Exception as e:
                job.update(state='failed', error=str(e))
        threading.Thread(target=run, daemon=True).start()
        return {'started': True}

    def work(self, name): return self.store.home / 'training' / name

    def running(self):
        if self.proc is not None: return self.proc.poll() is None
        return self.orphan() is not None

    def orphan(self):
        """A job started before this service (re)started: its PID file names it; it counts while that process lives."""
        base = self.store.home / 'training'
        for f in base.glob('*/job.pid') if base.exists() else []:
            try:
                pid = int(f.read_text())
                cmd = Path(f'/proc/{pid}/cmdline').read_bytes() if Path(f'/proc/{pid}').exists() else b''
                if b'build_dataset.py' in cmd or b'train.py' in cmd or b'train_vocoder.py' in cmd:   # its own command line only
                    self.name = f.parent.name; return pid
            except (OSError, ValueError):
                continue
        return None

    def has_gpu(self):
        if self.gpu is None:
            import subprocess
            py, _ = self.env()
            try: self.gpu = bool(py) and subprocess.run([str(py), '-c', 'import torch; print(torch.cuda.is_available())'], capture_output=True, text=True, timeout=60).stdout.strip() == 'True'
            except Exception: self.gpu = False
        return self.gpu

    def status(self, name):
        b = self.store.booth(name)
        minutes = 0.0
        for lid, k in b['kept'].items():
            f = self.store.dataset(name) / 'raw' / f'{lid}_{k}.wav'
            if f.exists(): minutes += sf.info(f).duration / 60
        w = self.work(name)
        state = json.loads((w / 'state.json').read_text()) if (w / 'state.json').exists() else {}
        log = (w / 'train.log').read_text(errors='replace')[-6000:] if (w / 'train.log').exists() else ''
        steps = re.findall(r'steps=(\d+)', log)
        py, _ = self.env()
        return {'name': name, 'kept': len(b['kept']), 'lines': len(self.store.script(name)), 'minutes': round(minutes, 1), 'min_minutes': MIN_MINUTES,
                'installed': py is not None, 'kit': self.kit_job, 'gpu': self.has_gpu() if py else False,
                'running': self.running() and self.name == name, 'busy_with': self.name if self.running() else None,
                'state': state, 'step': int(steps[-1]) if steps else None,
                'log': '\n'.join(l.split('\r')[-1] for l in log.splitlines()[-12:]),
                'voice': name in self.store.voice_dirs(), 'exit': None if self.proc is None or self.running() else self.proc.returncode}

    def start(self, name, steps=160000, smoke=False, vocoder=False):
        import subprocess
        if self.running(): raise ValueError(f'already training "{self.name}"')
        py, tdir = self.env()
        if not py: raise ValueError('the training kit is not installed yet (Training page: Install the training kit)')
        st = self.status(name)
        if not smoke and st['minutes'] < MIN_MINUTES: raise ValueError(f'{st["minutes"]} min recorded; record at least {MIN_MINUTES} min first')
        w = self.work(name); w.mkdir(parents=True, exist_ok=True)
        data = self.store.home / 'train' / name
        voices = self.store.home / 'voices'
        q = lambda x: f'"{x}"'
        steps_ = [f'{q(py)} {q(tdir / "build_dataset.py")} --booth {q(self.store.dataset(name))} --out {q(data)}',
                  f'{q(py)} {q(tdir / "train.py")} --data {q(data)} --name {q(name)} --steps {int(steps)} --voices {q(voices)}' + (' --smoke' if smoke else '')]
        if vocoder:      # then the voice's own small vocoder (fast on a CPU), and the voice switched to it
            steps_ += [f'{q(py)} {q(tdir / "train_vocoder.py")} --data {q(data)} --name {q(name)} --voices {q(voices)}' + (' --smoke' if smoke else ''),
                       f'{q(py)} {q(tdir / "train.py")} --data {q(data)} --name {q(name)} --only export --vocoder own --voices {q(voices)}']
        log = open(w / 'train.log', 'a')
        group = {'creationflags': 0x00000200 | 0x08000000} if os.name == 'nt' else {'start_new_session': True}   # own group, no console
        self.proc = subprocess.Popen(' && '.join(steps_), shell=True, stdout=log, stderr=subprocess.STDOUT, **group)
        self.name = name
        (w / 'job.pid').write_text(str(self.proc.pid))
        return {'started': True, 'pid': self.proc.pid}

    def stop(self):
        import signal, subprocess
        if not self.running(): return {'stopped': False}
        pid = self.proc.pid if self.proc is not None else self.orphan()
        if os.name == 'nt': subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)   # the job's tree only
        else: os.killpg(pid, signal.SIGTERM)                                                                    # its own process group
        return {'stopped': True}


class Handler(BaseHTTPRequestHandler):
    store: Store = None
    trainer: Trainer = None
    downloads: Downloads = None
    bridge: Bridge = None

    def log_message(self, *a): pass

    def send(self, code, body, ctype='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header('content-type', ctype); self.send_header('content-length', str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def route(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = re.sub(r'^/api/singer', '', unquote(u.path))      # project names arrive URL-encoded ("My%20song")
        name = q.get('name', 'you')
        return path, q, name

    def do_GET(self):
        try:
            path, q, name = self.route()
            if path == '/script': return self.send(200, self.store.script(name))
            if path == '/voices':
                from engine.song import LANGS
                return self.send(200, {'voices': self.store.voices(), 'modes': list(MODES), 'langs': LANGS})
            if path == '/projects':
                return self.send(200, sorted([{'name': f.stem, 'modified': f.stat().st_mtime} for f in self.store.projects_dir().glob('*.msing')], key=lambda x: -x['modified']))
            if path.startswith('/projects/'):
                f = self.store.project_file(path[len('/projects/'):])
                return self.send(200, json.loads(f.read_text())) if f.exists() else self.send(404, {'error': 'no such project'})
            if (m := re.match(r'^/render/([0-9a-f]{20})\.wav$', path)):
                f = self.store.home / 'cache' / f'{m.group(1)}.wav'
                return self.send(200, f.read_bytes(), 'audio/wav') if f.exists() else self.send(404, {'error': 'not rendered'})
            if (m := re.match(r'^/voices/([\w-]+)/icon\.png$', path)):
                d = self.store.voice_dirs().get(m.group(1))
                return self.send(200, (d / 'icon.png').read_bytes(), 'image/png') if d and (d / 'icon.png').exists() else self.send(404, {'error': 'no image'})
            if path == '/booth/progress': return self.send(200, self.store.progress(name))
            if path == '/train/status': return self.send(200, self.trainer.status(name))
            if path == '/downloads': return self.send(200, self.downloads.status())
            if path == '/bridge': return self.send(200, self.bridge.status())
            if (m := re.match(r'^/bridge/([0-9a-f]{16})\.wav$', path)):
                f = self.store.home / 'bridge' / m.group(1) / 'vocal.wav'
                return self.send(200, f.read_bytes(), 'audio/wav') if f.exists() else self.send(404, {'error': 'not converted'})
            if (m := re.match(r'^/backing/([0-9a-f]{40}\.(wav|mp3|flac|ogg))$', path)):
                f = self.store.home / 'backing' / m.group(1)
                types = {'wav': 'audio/wav', 'mp3': 'audio/mpeg', 'flac': 'audio/flac', 'ogg': 'audio/ogg'}
                return self.send(200, f.read_bytes(), types[m.group(2)]) if f.exists() else self.send(404, {'error': 'no such backing track'})
            if path.startswith('/mix/'):            # the DAW plugin on another computer: what to play, with download urls
                f = self.store.project_file(path[len('/mix/'):]).with_suffix('.mix.json')
                if not f.exists(): return self.send(404, {'error': 'not rendered yet: render it in Mortiflix Singer'})
                mix = json.loads(f.read_text())
                for t in mix['tracks']:
                    for ph in t['phrases']: ph['url'] = f"/api/singer/render/{Path(ph['file']).stem}.wav"; ph.pop('file', None)
                return self.send(200, mix)
            if path == '/autosave':                 # the newest unsaved editor state (project recovery)
                d = self.store.home / 'projects' / '.autosave'
                fs = sorted(d.glob('*.json'), key=lambda f: -f.stat().st_mtime) if d.exists() else []
                return self.send(200, json.loads(fs[0].read_text()) if fs else {})
            if path == '/scripts':                     # editor scripts: bundled examples + your own (~/MortiflixSinger/scripts)
                out = []
                for base, kind in ((HERE / 'scripts', 'bundled'), (self.store.home / 'scripts', 'yours')):
                    for f in sorted(base.glob('*.js')) if base.exists() else []:
                        m = re.search(r"export const title = ['\"](.+?)['\"]", f.read_text(errors='replace'))
                        out.append({'file': f'{kind}/{f.name}', 'title': m.group(1) if m else f.stem, 'kind': kind})
                return self.send(200, out)
            if (m := re.match(r'^/scripts/(bundled|yours)/([\w.-]+\.js)$', path)):
                f = (HERE / 'scripts' if m.group(1) == 'bundled' else self.store.home / 'scripts') / m.group(2)
                return self.send(200, f.read_bytes(), 'text/javascript') if f.exists() else self.send(404, {'error': 'no such script'})
            if (m := re.match(r'^/tune/file/([0-9a-f]{40}(?:-tuned)?\.wav)$', path)):
                f = self.store.home / 'tune' / m.group(1)
                return self.send(200, f.read_bytes(), 'audio/wav') if f.exists() else self.send(404, {'error': 'no such file'})
            if path == '/inbox':                       # MIDI sent from the DAW plugin
                d = self.store.home / 'inbox'
                files = sorted(d.glob('*.mid'), key=lambda f: -f.stat().st_mtime) if d.exists() else []
                return self.send(200, [{'name': f.name, 'modified': f.stat().st_mtime} for f in files])
            if path.startswith('/inbox/'):
                f = self.store.home / 'inbox' / Path(path[len('/inbox/'):]).name
                return self.send(200, formats.load(f.read_bytes(), f.name)) if f.suffix == '.mid' and f.exists() else self.send(404, {'error': 'not in the inbox'})
            if path == '/booth/take.wav':
                if not ID.match(q.get('id', '')): return self.send(400, {'error': 'bad id'})
                f = self.store.dataset(name) / 'raw' / f"{q['id']}_{int(q.get('take', 1))}.wav"
                return self.send(200, f.read_bytes(), 'audio/wav') if f.exists() else self.send(404, {'error': 'no such take'})
            self.send(404, {'error': 'not found'})
        except Exception as e:
            self.send(500, {'error': str(e)})

    def do_POST(self):
        try:
            path, q, name = self.route()
            n = int(self.headers.get('content-length', 0))
            body = self.rfile.read(n) if n else b''
            if path == '/booth/take':
                lid = q.get('id', '')
                if not ID.match(lid) or not self.store.line(name, lid): return self.send(400, {'error': 'unknown line'})
                y, sr = sf.read(io.BytesIO(body), dtype='float32')
                g = grade(y, sr, self.store.line(name, lid), preroll_s=float(q.get('preroll', 0)))
                with lock:
                    b = self.store.booth(name)
                    takes = b['takes'].setdefault(lid, [])
                    k = len(takes) + 1
                    sf.write(self.store.dataset(name) / 'raw' / f'{lid}_{k}.wav', y, sr, subtype='PCM_24')
                    takes.append({'take': k, 'grade': g['grade'], 'at': time.time(), 'report': g,
                                  'key_offset': g.get('key_offset'), 'preroll': float(q.get('preroll', 0))})
                    if g['grade'] in ('A', 'B'):     # the best take so far is the one kept
                        best = min(takes, key=lambda t: ('ABC'.index(t['grade']), -t['take']))
                        b['kept'][lid] = best['take']
                    self.store.save_booth(name, b)
                return self.send(200, {'take': k, **g})
            if path == '/render':
                req = json.loads(body)
                project, quality = expand_groups(req['project']), req.get('quality', 'final')
                tracks = [t for t in project['tracks'] if not req.get('track') or t['id'] == req['track']]
                result, mix = {}, {}
                with self.store.render_lock:
                    for t in tracks:
                        if not t['notes']: result[t['id']] = []; continue
                        v = self.store.voice(t.get('voice') or 'SPORE')
                        phrases = render_track(v, t.get('voice') or 'SPORE', project, t, self.store.home / 'cache', quality)
                        if req.get('name') and quality == 'final': mix[t['id']] = [{'start_ms': m['start_ms'], 'file': m['file']} for m in phrases]
                        for m in phrases: m.pop('file', None); m['url'] = f"/api/singer/render/{m['hash']}.wav"
                        result[t['id']] = phrases
                if req.get('name') and quality == 'final' and len(tracks) == len(project['tracks']):
                    self.store.write_mix(req['name'], project, mix)
                return self.send(200, {'tracks': result})
            if path == '/check':
                from engine.checks import check_track
                req = json.loads(body); project = expand_groups(req['project'])
                out = {}
                with self.store.render_lock:
                    for t in project['tracks']:
                        if req.get('track') and t['id'] != req['track'] or not t['notes']: continue
                        v = self.store.voice(t.get('voice') or 'SPORE')
                        phrases = render_track(v, t.get('voice') or 'SPORE', project, t, self.store.home / 'cache', 'final')
                        out[t['id']] = check_track(project, t, phrases, diction=req.get('diction', True))
                return self.send(200, {'tracks': out})
            if path == '/phonemize':
                req = json.loads(body)
                v = self.store.voice(req.get('voice') or 'SPORE')
                return self.send(200, {'phonemes': {w: phonemize(w, v.tokens, req.get('lang', 'en')) for w in req.get('words', [])}})
            if path.startswith('/projects/'):
                f = self.store.project_file(path[len('/projects/'):])
                project = json.loads(body)
                tmp = f.with_suffix('.tmp'); tmp.write_text(json.dumps(project)); tmp.replace(f)
                return self.send(200, {'ok': True, 'name': f.stem})
            if path == '/autosave':
                req = json.loads(body); d = self.store.home / 'projects' / '.autosave'; d.mkdir(parents=True, exist_ok=True)
                key = re.sub(r'[^\w .()-]', '', req.get('name') or 'untitled')[:80] or 'untitled'
                f = d / f'{key}.json'; tmp = f.with_suffix('.tmp')
                tmp.write_text(json.dumps({'name': req.get('name'), 'project': req['project'], 'at': time.time()})); tmp.replace(f)
                return self.send(200, {'ok': True})
            if path == '/backing':                     # an instrumental to sing against: stored by content, played in sync
                import hashlib
                ext = Path(q.get('filename', 'x.wav')).suffix.lower().lstrip('.')
                if ext not in ('wav', 'mp3', 'flac', 'ogg'): return self.send(400, {'error': 'use a WAV, MP3, FLAC or OGG file'})
                d = self.store.home / 'backing'; d.mkdir(parents=True, exist_ok=True)
                f = d / f'{hashlib.sha1(body).hexdigest()}.{ext}'
                if not f.exists(): f.write_bytes(body)
                try: dur = sf.info(f).duration
                except Exception: dur = None
                return self.send(200, {'file': f.name, 'name': q.get('filename', f.name), 'duration': dur})
            if path == '/bridge':
                req = json.loads(body)
                return self.send(200, self.bridge.start(req['project'], req.get('transpose', 0)))
            if path == '/tune/upload':                 # the pitch corrector's inputs: a vocal (stored as WAV) or a MIDI part
                import hashlib
                d = self.store.home / 'tune'; d.mkdir(parents=True, exist_ok=True)
                name = q.get('filename', 'x.wav'); h = hashlib.sha1(body).hexdigest()
                if name.lower().endswith(('.mid', '.midi')):
                    f = d / f'{h}.mid'; f.write_bytes(body)
                    from engine.song import read_midi
                    notes = read_midi(str(f), None)
                    return self.send(200, {'file': f.name, 'notes': [[round(a_, 1), round(b_, 1), int(m_)] for a_, b_, m_ in notes]})
                y, sr = sf.read(io.BytesIO(body), dtype='float32', always_2d=True)
                f = d / f'{h}.wav'; sf.write(f, y.mean(1), sr, subtype='FLOAT')
                return self.send(200, {'file': f.name, 'duration': round(len(y) / sr, 2), 'sample_rate': sr})
            if path == '/tune':
                from engine.correct import correct
                req = json.loads(body); d = self.store.home / 'tune'
                wav = d / Path(req['wav']).name
                y, sr = sf.read(wav, dtype='float32')
                notes = [(a_ + req.get('offset_ms', 0), b_, m_) for a_, b_, m_ in req['notes']] if req.get('notes') else None
                key = (int(req['key']['root']), req['key'].get('scale', 'major')) if req.get('key') else None
                out, rep = correct(y, sr, notes=notes, key=key, amount=float(req.get('amount', 1.0)),
                                   speed=float(req.get('speed', 60)), vibrato=bool(req.get('vibrato', True)))
                o = d / f'{wav.stem}-tuned.wav'; sf.write(o, out, sr, subtype='PCM_24')
                return self.send(200, {**rep, 'file': o.name, 'url': f'/api/singer/tune/file/{o.name}', 'original': f'/api/singer/tune/file/{wav.name}'})
            if path == '/import':
                return self.send(200, formats.load(body, q.get('filename', 'file.mid')))
            if path == '/export':
                req = json.loads(body); kind = req.get('format', 'wav')
                project = req['project'] if kind == 'msing' else expand_groups(req['project'])   # .msing keeps its groups
                if kind == 'mid': return self.send(200, formats.to_midi(project), 'audio/midi')
                if kind == 'musicxml': return self.send(200, formats.to_musicxml(project), 'application/vnd.recordare.musicxml+xml')
                if kind == 'msing': return self.send(200, json.dumps(project, indent=1).encode(), 'application/json')
                results, sr = {}, 44100
                with self.store.render_lock:
                    for t in project['tracks']:
                        if not t['notes']: continue
                        v = self.store.voice(t.get('voice') or 'SPORE'); sr = v.sr
                        results[t['id']] = render_track(v, t.get('voice') or 'SPORE', project, t, self.store.home / 'cache', 'final')
                if kind == 'stems':                    # every track on its own, from bar 1, in one zip
                    import zipfile
                    from scipy.signal import resample_poly
                    from math import gcd
                    rate = int(req.get('sample_rate') or sr); bits_ = {'16': 'PCM_16', '24': 'PCM_24', '32': 'FLOAT'}.get(str(req.get('bits', 24)), 'PCM_24')
                    end = max((m['end_ms'] for r in results.values() for m in r), default=0)
                    zbuf = io.BytesIO()
                    with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as z:
                        for t in project['tracks']:
                            if t['id'] not in results: continue
                            one = mixdown(sr, project, {t['id']: results[t['id']]}, [{**t, 'mute': False, 'solo': False}])
                            one = np.pad(one, ((0, max(0, int((end / 1000 + 0.5) * sr) - len(one))), (0, 0)))
                            if rate != sr: g = gcd(rate, sr); one = resample_poly(one, rate // g, sr // g, axis=0).astype(np.float32)
                            w = io.BytesIO(); sf.write(w, one, rate, subtype=bits_, format='WAV')
                            z.writestr(f"{re.sub(r'[^\w .()-]', '', t.get('name') or t['id'])}.wav", w.getvalue())
                    return self.send(200, zbuf.getvalue(), 'application/zip')
                tracks = [t for t in project['tracks'] if not req.get('track') or t['id'] == req['track']]
                mix = mixdown(sr, project, results, tracks)
                bk = project.get('backing') or {}
                if req.get('include_backing') and bk.get('file') and not bk.get('mute'):
                    y, bsr = sf.read(self.store.home / 'backing' / Path(bk['file']).name, dtype='float32', always_2d=True)
                    if bsr != sr:
                        from scipy.signal import resample_poly
                        y = resample_poly(y, sr, bsr, axis=0).astype(np.float32)
                    y = (y if y.shape[1] == 2 else np.repeat(y[:, :1], 2, 1)) * 10 ** (bk.get('gain_db', 0) / 20)
                    a0 = int(round(bk.get('offset_ms', 0) / 1000 * sr))
                    if a0 < 0: y, a0 = y[-a0:], 0
                    if len(mix) < a0 + len(y): mix = np.concatenate([mix, np.zeros((a0 + len(y) - len(mix), 2), np.float32)])
                    mix[a0:a0 + len(y)] += y
                rate = int(req.get('sample_rate') or sr)
                if rate != sr:                       # 48 kHz for video work: one high-quality resample of the finished mix
                    from scipy.signal import resample_poly
                    from math import gcd
                    g = gcd(rate, sr); mix = resample_poly(mix, rate // g, sr // g, axis=0).astype(np.float32); sr = rate
                bits = {'16': 'PCM_16', '24': 'PCM_24', '32': 'FLOAT'}.get(str(req.get('bits', 24)), 'PCM_24')
                buf = io.BytesIO(); sf.write(buf, mix, sr, subtype=bits, format='WAV')
                return self.send(200, buf.getvalue(), 'audio/wav')
            if path == '/booth/songs':              # set D: lines from one of your song projects
                req = json.loads(body)
                proj = req.get('project') or json.loads(self.store.project_file(req['name']).read_text())
                return self.send(200, {'added': len(self.store.add_song(name, proj))})
            if path == '/train/start':
                req = json.loads(body or b'{}')
                return self.send(200, self.trainer.start(name, int(req.get('steps', 160000)), bool(req.get('smoke')), bool(req.get('vocoder'))))
            if path == '/train/stop': return self.send(200, self.trainer.stop())
            if path == '/train/kit': return self.send(200, self.trainer.install_kit())
            if path == '/downloads/start': return self.send(200, self.downloads.start(q.get('id', '')))
            if path == '/booth/keep':
                with lock:
                    b = self.store.booth(name); lid = q.get('id', '')
                    if lid not in b['takes']: return self.send(404, {'error': 'no takes'})
                    b['kept'][lid] = int(q.get('take', 1)); self.store.save_booth(name, b)
                return self.send(200, {'ok': True})
            self.send(404, {'error': 'not found'})
        except Exception as e:
            self.send(500, {'error': str(e)})


if hasattr(socketserver, 'UnixStreamServer'):          # not on Windows: there the app uses --stdio
    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

        def get_request(self):
            req, _ = super().get_request()
            return req, ('local', 0)      # BaseHTTPRequestHandler wants a (host, port) pair
else:
    Server = None


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve_stdio():
    """The desktop app's transport: no socket file, no port. Each request arrives on stdin as a line of JSON
    {"id": n, "len": N} followed by N bytes of a raw HTTP request; each answer goes to stdout the same way, raw HTTP
    response bytes. Requests run in parallel threads; the handler code is the same as over the socket (each request is
    played through a socket pair)."""
    import socket
    out, out_lock = sys.stdout.buffer, threading.Lock()
    sys.stdout = sys.stderr                     # stray prints must never corrupt the frames

    class One:                                  # the minimum of a server a handler needs
        pass

    def answer(rid, raw):
        a, b = socket.socketpair()
        try:
            a.sendall(raw); a.shutdown(socket.SHUT_WR)
            t = threading.Thread(target=lambda: (Handler(b, ('local', 0), One()), b.close()), daemon=True); t.start()
            chunks = []
            while (c := a.recv(1 << 16)): chunks.append(c)
            data = b''.join(chunks)
        finally:
            a.close()
        with out_lock:
            out.write(json.dumps({'id': rid, 'len': len(data)}).encode() + b'\n' + data); out.flush()

    inp, live = sys.stdin.buffer, []
    while (line := inp.readline()):
        if not line.strip(): continue
        h = json.loads(line); raw = inp.read(h['len'])
        t = threading.Thread(target=answer, args=(h['id'], raw), daemon=True); t.start()
        live = [x for x in live if x.is_alive()] + [t]
    for t in live: t.join()                     # the app closed our input: finish what was asked, then stop


def main():
    ap = argparse.ArgumentParser()
    home = Path(os.environ.get('SINGER_HOME', Path.home() / 'MortiflixSinger'))
    ap.add_argument('--home', default=str(home)); ap.add_argument('--socket')
    ap.add_argument('--stdio', action='store_true', help='serve requests framed on stdin/stdout (the desktop app)')
    ap.add_argument('--port', type=int, help='serve on 127.0.0.1:PORT instead of a socket file (Windows development)')
    a = ap.parse_args()
    home = Path(a.home); home.mkdir(parents=True, exist_ok=True)
    if a.stdio:
        Handler.store = Store(home); Handler.trainer = Trainer(Handler.store); Handler.downloads = Downloads(Handler.store); Handler.bridge = Bridge(Handler.store)
        return serve_stdio()
    if a.port or Server is None:
        if not a.port: raise SystemExit('this system has no socket files: use --stdio, or --port N for a loopback port')
        Handler.store = Store(home); Handler.trainer = Trainer(Handler.store); Handler.downloads = Downloads(Handler.store); Handler.bridge = Bridge(Handler.store)
        srv = TCPServer(('127.0.0.1', a.port), Handler)
        print(f'singer service on 127.0.0.1:{a.port}', flush=True)
        return srv.serve_forever()
    sock = Path(a.socket or home / 'singer.sock')
    if sock.exists(): sock.unlink()
    Handler.store = Store(home); Handler.trainer = Trainer(Handler.store); Handler.downloads = Downloads(Handler.store); Handler.bridge = Bridge(Handler.store)
    srv = Server(str(sock), Handler)
    os.chmod(sock, 0o600)
    print(f'singer service on {sock}', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
