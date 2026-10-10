#!/usr/bin/env python3
"""The singer service: the Booth's script, takes and grades (and later rendering), over a UNIX socket so no TCP port
is opened. Mortiflix Music forwards /api/singer/* to it and serves the web pages at /singer/.

  server.py [--socket ~/MortiflixSinger/singer.sock] [--home ~/MortiflixSinger]
"""
import argparse, io, json, os, re, socketserver, sys, threading, time, warnings
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import numpy as np, soundfile as sf

warnings.filterwarnings('ignore')
HERE = Path(__file__).parent
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
            for cfg in base.glob('**/dsconfig.yaml'):
                d = cfg.parent
                if d.name in ('dsdur', 'dspitch', 'dsvariance'): continue
                found.setdefault(d.name, d)
        return found

    def vocoder_dir(self):
        for base in (self.home / 'voices', HERE / 'voices'):
            if (base / 'nsf_hifigan' / 'vocoder.yaml').exists(): return base / 'nsf_hifigan'
        raise FileNotFoundError('no vocoder: put the OpenVPI NSF-HiFiGAN in voices/nsf_hifigan')

    def voice(self, name):
        from engine.ds import Voice
        if name not in self.voices_cache:
            dirs = self.voice_dirs()
            if name not in dirs: raise ValueError(f'no voice "{name}" (installed: {", ".join(dirs) or "none"})')
            self.voices_cache[name] = Voice(dirs[name], self.vocoder_dir())
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


class Handler(BaseHTTPRequestHandler):
    store: Store = None

    def log_message(self, *a): pass

    def send(self, code, body, ctype='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header('content-type', ctype); self.send_header('content-length', str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def route(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = re.sub(r'^/api/singer', '', u.path)
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
                result = {}
                with self.store.render_lock:
                    for t in tracks:
                        if not t['notes']: result[t['id']] = []; continue
                        v = self.store.voice(t.get('voice') or 'SPORE')
                        phrases = render_track(v, t.get('voice') or 'SPORE', project, t, self.store.home / 'cache', quality)
                        for m in phrases: m.pop('file', None); m['url'] = f"/api/singer/render/{m['hash']}.wav"
                        result[t['id']] = phrases
                return self.send(200, {'tracks': result})
            if path == '/phonemize':
                req = json.loads(body)
                v = self.store.voice(req.get('voice') or 'SPORE')
                return self.send(200, {'phonemes': {w: phonemize(w, v.tokens) for w in req.get('words', [])}})
            if path.startswith('/projects/'):
                f = self.store.project_file(path[len('/projects/'):])
                project = json.loads(body)
                tmp = f.with_suffix('.tmp'); tmp.write_text(json.dumps(project)); tmp.replace(f)
                return self.send(200, {'ok': True, 'name': f.stem})
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
                bits = {'16': 'PCM_16', '24': 'PCM_24', '32': 'FLOAT'}.get(str(req.get('bits', 24)), 'PCM_24')
                buf = io.BytesIO(); sf.write(buf, mix, sr, subtype=bits, format='WAV')
                return self.send(200, buf.getvalue(), 'audio/wav')
            if path == '/booth/keep':
                with lock:
                    b = self.store.booth(name); lid = q.get('id', '')
                    if lid not in b['takes']: return self.send(404, {'error': 'no takes'})
                    b['kept'][lid] = int(q.get('take', 1)); self.store.save_booth(name, b)
                return self.send(200, {'ok': True})
            self.send(404, {'error': 'not found'})
        except Exception as e:
            self.send(500, {'error': str(e)})


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self):
        req, _ = super().get_request()
        return req, ('local', 0)      # BaseHTTPRequestHandler wants a (host, port) pair


def main():
    ap = argparse.ArgumentParser()
    home = Path(os.environ.get('SINGER_HOME', Path.home() / 'MortiflixSinger'))
    ap.add_argument('--home', default=str(home)); ap.add_argument('--socket')
    a = ap.parse_args()
    home = Path(a.home); home.mkdir(parents=True, exist_ok=True)
    sock = Path(a.socket or home / 'singer.sock')
    if sock.exists(): sock.unlink()
    Handler.store = Store(home)
    srv = Server(str(sock), Handler)
    os.chmod(sock, 0o600)
    print(f'singer service on {sock}', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
