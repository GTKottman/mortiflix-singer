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
from engine.project import render_track, mixdown, new_project, MODES
from engine.song import phonemes as phonemize

VOICE_INFO = {   # what we know about voices that don't say it themselves
    'SPORE': {'range': ['F#3', 'G4'], 'license': 'CC BY-NC-ND 4.0: non-commercial use only, credit Knoxstation', 'commercial': False},
}

SCRIPT = json.loads((HERE / 'booth/script.json').read_text())
LINES = {r['id']: r for r in SCRIPT}
ID = re.compile(r'^[A-Z]\d{4}$')
NAME = re.compile(r'^[a-z0-9_-]{1,40}$')
lock = threading.Lock()


class Store:
    def __init__(self, home: Path):
        self.home = home
        self.voices_cache, self.render_lock = {}, threading.Lock()

    # ---- voices ----
    def voice_dirs(self):
        found = {}
        for base in (self.home / 'voices', HERE / 'voices'):
            if not base.exists(): continue
            for top, dirs, files in os.walk(base, followlinks=True):    # voices may be linked in from elsewhere
                if 'dsconfig.yaml' not in files: continue
                d = Path(top)
                if d.name in ('dsdur', 'dspitch', 'dsvariance'): continue
                found.setdefault(d.name, d)
        return found

    def vocoder_dir(self, want=None):
        """The vocoder a voice asks for in its dsconfig ('vocoder: <name>'), found by its vocoder.yaml name or folder;
        voices that don't say (or say nsf_hifigan) get the OpenVPI NSF-HiFiGAN."""
        import yaml
        want = want or 'nsf_hifigan'
        for base in (self.home / 'voices', HERE / 'voices'):
            if not base.exists(): continue
            for y in base.glob('*/vocoder.yaml'):
                name = (yaml.safe_load(y.read_text()) or {}).get('name', '')
                if want in (y.parent.name, name) or (want == 'nsf_hifigan' and y.parent.name == 'nsf_hifigan'): return y.parent
        hint = 'install it on the Singer home page (Voices)'
        raise FileNotFoundError(f'no vocoder "{want}" yet: {hint}')

    def voice(self, name):
        from engine.ds import Voice
        if name not in self.voices_cache:
            dirs = self.voice_dirs()
            if name not in dirs: raise ValueError(f'no voice "{name}" (installed: {", ".join(dirs) or "none"})')
            import yaml
            want = (yaml.safe_load((dirs[name] / 'dsconfig.yaml').read_text()) or {}).get('vocoder')
            self.voices_cache[name] = Voice(dirs[name], self.vocoder_dir(want))
        return self.voices_cache[name]

    def voices(self):
        out = []
        for name, d in self.voice_dirs().items():
            info = {'name': name, **VOICE_INFO.get(name, {'range': None, 'license': 'see the voice folder', 'commercial': None})}
            info['image'] = (d / 'icon.png').exists()
            out.append(info)
        return out

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

    def progress(self, name):
        b = self.booth(name)
        sets = {}
        for r in SCRIPT:
            s = sets.setdefault(r['set'], {'lines': 0, 'kept': 0})
            s['lines'] += 1; s['kept'] += r['id'] in b['kept']
        nxt = next((r['id'] for r in SCRIPT if r['id'] not in b['kept']), None)
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
        d = self.store.home / 'voices' / DOWNLOADS[key]['dest']
        return d.exists() and any(d.rglob('vocoder.yaml' if key in ('vocoder', 'bigvgan') else 'dsconfig.yaml'))

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


MIN_MINUTES = 30        # below this a voice is too thin to be worth hours of training (DiffSinger asks for about an hour)
TRAIN_PY = HERE / 'trainer' / '.venv' / 'bin' / 'python'


class Trainer:
    """One training job at a time, in the background: Booth takes -> dataset -> DiffSinger -> a voice in voices/.
    The job runs as its own process (PID kept, stopped by PID only) so the service stays free to render."""
    def __init__(self, store):
        self.store, self.proc, self.name, self.gpu = store, None, None, None

    def work(self, name): return self.store.home / 'training' / name

    def running(self): return self.proc is not None and self.proc.poll() is None

    def has_gpu(self):
        if self.gpu is None:
            import subprocess
            try: self.gpu = subprocess.run([str(TRAIN_PY), '-c', 'import torch; print(torch.cuda.is_available())'], capture_output=True, text=True, timeout=60).stdout.strip() == 'True'
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
        return {'name': name, 'kept': len(b['kept']), 'lines': len(SCRIPT), 'minutes': round(minutes, 1), 'min_minutes': MIN_MINUTES,
                'installed': TRAIN_PY.exists(), 'gpu': self.has_gpu() if TRAIN_PY.exists() else False,
                'running': self.running() and self.name == name, 'busy_with': self.name if self.running() else None,
                'state': state, 'step': int(steps[-1]) if steps else None,
                'log': '\n'.join(l.split('\r')[-1] for l in log.splitlines()[-12:]),
                'voice': name in self.store.voice_dirs(), 'exit': None if self.proc is None or self.running() else self.proc.returncode}

    def start(self, name, steps=160000, smoke=False):
        import subprocess
        if self.running(): raise ValueError(f'already training "{self.name}"')
        if not TRAIN_PY.exists(): raise ValueError('the training environment is not installed: run trainer/setup.sh')
        st = self.status(name)
        if not smoke and st['minutes'] < MIN_MINUTES: raise ValueError(f'{st["minutes"]} min recorded; record at least {MIN_MINUTES} min first')
        w = self.work(name); w.mkdir(parents=True, exist_ok=True)
        data = self.store.home / 'train' / name
        script = (f'"{TRAIN_PY}" "{HERE}/trainer/build_dataset.py" --booth "{self.store.dataset(name)}" --out "{data}" '
                  f'&& "{TRAIN_PY}" "{HERE}/trainer/train.py" --data "{data}" --name "{name}" --steps {int(steps)}'
                  f' --voices "{self.store.home}/voices"' + (' --smoke' if smoke else ''))
        log = open(w / 'train.log', 'a')
        self.proc = subprocess.Popen(['bash', '-c', script], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.name = name
        (w / 'job.pid').write_text(str(self.proc.pid))
        return {'started': True, 'pid': self.proc.pid}

    def stop(self):
        import signal
        if not self.running(): return {'stopped': False}
        os.killpg(self.proc.pid, signal.SIGTERM)     # its own process group: the job and only the job
        return {'stopped': True}


class Handler(BaseHTTPRequestHandler):
    store: Store = None
    trainer: Trainer = None
    downloads: Downloads = None

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
            if path == '/script': return self.send(200, SCRIPT)
            if path == '/voices': return self.send(200, {'voices': self.store.voices(), 'modes': list(MODES)})
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
            if (m := re.match(r'^/backing/([0-9a-f]{40}\.(wav|mp3|flac|ogg))$', path)):
                f = self.store.home / 'backing' / m.group(1)
                types = {'wav': 'audio/wav', 'mp3': 'audio/mpeg', 'flac': 'audio/flac', 'ogg': 'audio/ogg'}
                return self.send(200, f.read_bytes(), types[m.group(2)]) if f.exists() else self.send(404, {'error': 'no such backing track'})
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
                if not ID.match(lid) or lid not in LINES: return self.send(400, {'error': 'unknown line'})
                y, sr = sf.read(io.BytesIO(body), dtype='float32')
                g = grade(y, sr, LINES[lid], preroll_s=float(q.get('preroll', 0)))
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
                project, quality = req['project'], req.get('quality', 'final')
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
                req = json.loads(body); project = req['project']
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
                return self.send(200, {'phonemes': {w: phonemize(w, v.tokens) for w in req.get('words', [])}})
            if path.startswith('/projects/'):
                f = self.store.project_file(path[len('/projects/'):])
                project = json.loads(body)
                tmp = f.with_suffix('.tmp'); tmp.write_text(json.dumps(project)); tmp.replace(f)
                return self.send(200, {'ok': True, 'name': f.stem})
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
            if path == '/import':
                return self.send(200, formats.load(body, q.get('filename', 'file.mid')))
            if path == '/export':
                req = json.loads(body); project = req['project']; kind = req.get('format', 'wav')
                if kind == 'mid': return self.send(200, formats.to_midi(project), 'audio/midi')
                if kind == 'musicxml': return self.send(200, formats.to_musicxml(project), 'application/vnd.recordare.musicxml+xml')
                if kind == 'msing': return self.send(200, json.dumps(project, indent=1).encode(), 'application/json')
                results, sr = {}, 44100
                with self.store.render_lock:
                    for t in project['tracks']:
                        if not t['notes']: continue
                        v = self.store.voice(t.get('voice') or 'SPORE'); sr = v.sr
                        results[t['id']] = render_track(v, t.get('voice') or 'SPORE', project, t, self.store.home / 'cache', 'final')
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
                bits = {'16': 'PCM_16', '24': 'PCM_24', '32': 'FLOAT'}.get(str(req.get('bits', 24)), 'PCM_24')
                buf = io.BytesIO(); sf.write(buf, mix, sr, subtype=bits, format='WAV')
                return self.send(200, buf.getvalue(), 'audio/wav')
            if path == '/train/start':
                req = json.loads(body or b'{}')
                return self.send(200, self.trainer.start(name, int(req.get('steps', 160000)), bool(req.get('smoke'))))
            if path == '/train/stop': return self.send(200, self.trainer.stop())
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
        Handler.store = Store(home); Handler.trainer = Trainer(Handler.store); Handler.downloads = Downloads(Handler.store)
        return serve_stdio()
    if a.port or Server is None:
        if not a.port: raise SystemExit('this system has no socket files: use --stdio, or --port N for a loopback port')
        Handler.store = Store(home); Handler.trainer = Trainer(Handler.store); Handler.downloads = Downloads(Handler.store)
        srv = TCPServer(('127.0.0.1', a.port), Handler)
        print(f'singer service on 127.0.0.1:{a.port}', flush=True)
        return srv.serve_forever()
    sock = Path(a.socket or home / 'singer.sock')
    if sock.exists(): sock.unlink()
    Handler.store = Store(home); Handler.trainer = Trainer(Handler.store); Handler.downloads = Downloads(Handler.store)
    srv = Server(str(sock), Handler)
    os.chmod(sock, 0o600)
    print(f'singer service on {sock}', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
