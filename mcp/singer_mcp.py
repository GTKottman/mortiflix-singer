#!/usr/bin/env python3
"""Mortiflix Singer MCP server (stdio, no dependencies).

Tools write projects (notes + one lyric token per note), render them to WAV, check every word and note, import
MIDI / UST / SVP / VSQX / MusicXML, export, and follow voice training. Everything goes through the singer service
(started here if it isn't running), so renders share the editor's cache and projects appear in the editor.

Register with Claude Code:
    claude mcp add singer -s user -- python3 /path/to/singer/mcp/singer_mcp.py
"""
import http.client, json, os, socket, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get('SINGER_HOME', Path.home() / 'MortiflixSinger'))
SOCK = HOME / 'singer.sock'
STR, INT, NUM, BOOL = {'type': 'string'}, {'type': 'integer'}, {'type': 'number'}, {'type': 'boolean'}
LYRICS = ('One token per note, in time order: a word, "sun-" then "rise" for one word over two notes, "_" holds the '
          'vowel onto the next note, "." leaves a note silent, "br" is a breath, "word{ph ph}" spells ARPAbet phonemes.')


class Conn(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX); self.sock.settimeout(self.timeout); self.sock.connect(str(SOCK))


def ensure_service():
    """Start the singer service if its socket isn't answering; its PID goes to ~/MortiflixSinger/service.pid."""
    try:
        c = Conn('singer', timeout=5); c.request('GET', '/voices'); c.getresponse().read(); return
    except OSError:
        pass
    py = REPO / '.venv' / 'bin' / 'python'
    HOME.mkdir(parents=True, exist_ok=True)
    log = open(HOME / 'server.log', 'a')
    p = subprocess.Popen([str(py if py.exists() else sys.executable), str(REPO / 'server.py')], cwd=REPO,
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (HOME / 'service.pid').write_text(str(p.pid))
    for _ in range(100):
        time.sleep(0.2)
        if SOCK.exists():
            try:
                c = Conn('singer', timeout=5); c.request('GET', '/voices'); c.getresponse().read(); return
            except OSError:
                pass
    raise RuntimeError(f'the singer service did not start; see {HOME / "server.log"}')


def call(method, path, body=None, raw=False, timeout=1800):
    ensure_service()
    c = Conn('singer', timeout=timeout)
    data = body if raw else (json.dumps(body).encode() if body is not None else None)
    c.request(method, path.replace(' ', '%20'), data, {'content-type': 'application/octet-stream' if raw else 'application/json',
                                                        'content-length': str(len(data or b''))})
    r = c.getresponse(); out = r.read()
    if r.status >= 400:
        try: msg = json.loads(out).get('error')
        except Exception: msg = out[:300].decode(errors='replace')
        raise RuntimeError(msg)
    return out if r.getheader('content-type', '').startswith(('audio', 'application/vnd', 'application/octet')) else json.loads(out)


def new_project(title, bpm, ts=(4, 4)):
    return {'version': 1, 'ppq': 480, 'title': title, 'tempo': [{'tick': 0, 'bpm': bpm}], 'time_sig': list(ts), 'tracks': []}


def track(tid, name, voice, notes):
    return {'id': tid, 'name': name, 'voice': voice, 'mode': 'Default', 'mute': False, 'solo': False, 'gain_db': 0, 'pan': 0,
            'transpose': 0, 'notes': notes, 'lanes': {}, 'pitch_draw': [], 'params': {'expr': 1.0, 'correct': 1.0, 'steps': 20}}


def lay_lyrics(notes, lyrics):
    toks = lyrics.split()
    if len(toks) != len(notes):
        raise ValueError(f'{len(toks)} lyric tokens for {len(notes)} notes: they must match one to one. {LYRICS}')
    for n, t in zip(sorted(notes, key=lambda n: n['tick']), toks): n['lyric'] = t
    return notes


def load(name):
    return call('GET', f'/projects/{name}')


def save(name, project):
    return call('POST', f'/projects/{name}', project)


def summary(name, p):
    out = [f'"{name}": {p.get("title", "")} · {p["tempo"][0]["bpm"]} BPM · {"/".join(map(str, p["time_sig"]))}']
    for t in p['tracks']:
        ns = sorted(t['notes'], key=lambda n: n['tick'])
        out.append(f'  track {t["id"]} "{t["name"]}" voice {t["voice"]} mode {t.get("mode", "Default")}: {len(ns)} notes')
        if ns: out.append('    lyrics: ' + ' '.join(n.get('lyric') or 'la' for n in ns))
    if p.get('backing'): out.append(f'  backing: {p["backing"].get("name")}')
    return '\n'.join(out)


def render_wav(name, p, out, include_backing=False, bits=24):
    wav = call('POST', '/export', {'project': p, 'format': 'wav', 'bits': bits, 'include_backing': include_backing})
    out = Path(out).expanduser(); out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(wav)
    # render once more with the name, so the DAW plugin's mix file is current (phrases are cached: instant)
    call('POST', '/render', {'project': p, 'quality': 'final', 'name': name})
    return out


def check_text(p, track_id=None):
    r = call('POST', '/check', {'project': p, 'track': track_id})
    lines = []
    for tid, res in r['tracks'].items():
        s = res['summary']
        lines.append(f'track {tid}: {s["words"] - s["unclear"]} of {s["words"]} words clear, {s["off_notes"]} notes more than 20 cents off')
        for w in res['words']:
            if not w['ok']: lines.append(f'  unclear "{w["word"]}" (notes {",".join(w["notes"])}), heard: "{w["heard"]}"')
        for t in res['tuning']: lines.append(f'  note {t["note"]}: {t["cents"]:+d} cents')
    return '\n'.join(lines)


# ---- tools ----
def t_voices(a):
    v = call('GET', '/voices'); d = call('GET', '/downloads')
    lines = [f'{x["name"]}: range {x.get("range") or "?"}; {x.get("license")}' for x in v['voices']]
    for x in d:
        state = 'installed' if x['installed'] else f'{x["size_mb"]} MB'
        lines.append(f'download {x["id"]}: {x["title"]} ({state}); {x["license"]}')
    return '\n'.join(lines + [f'vocal modes: {", ".join(v["modes"])}'])


def t_sing(a):
    """notes [[beat, beats, midi], ...] + lyrics -> a saved project and a WAV."""
    bpm = float(a.get('bpm', 120)); ppq = 480
    notes = [{'id': f'n{i}', 'tick': round(b * ppq), 'dur': max(1, round(l * ppq)), 'pitch': int(m), 'vel': 64}
             for i, (b, l, m) in enumerate(a['notes'])]
    lay_lyrics(notes, a['lyrics'])
    name = a.get('project') or a.get('title') or 'Sung'
    p = new_project(a.get('title') or name, bpm); p['tracks'].append(track('t1', 'Lead', a.get('voice', 'SPORE'), notes))
    if a.get('mode'): p['tracks'][0]['mode'] = a['mode']
    save(name, p)
    out = render_wav(name, p, a.get('out') or HOME / 'out' / f'{name}.wav')
    msg = f'saved project "{name}", wrote {out}'
    if a.get('check', True): msg += '\n' + check_text(p)
    return msg


def t_import(a):
    path = Path(a['path']).expanduser()
    p = call('POST', f'/import?filename={path.name.replace(" ", "%20")}', path.read_bytes(), raw=True)
    if a.get('voice'):
        for t in p['tracks']: t['voice'] = a['voice']
    if a.get('lyrics'):
        t = next((t for t in p['tracks'] if t['id'] == a.get('track')), p['tracks'][0])
        lay_lyrics(t['notes'], a['lyrics'])
    name = a.get('project') or path.stem
    save(name, p)
    return 'imported\n' + summary(name, p)


def t_projects(a):
    ps = call('GET', '/projects')
    return '\n'.join(f'{x["name"]} (saved {time.strftime("%Y-%m-%d %H:%M", time.localtime(x["modified"]))})' for x in ps) or 'no projects yet'


def t_show(a): return summary(a['project'], load(a['project']))


def t_lyrics(a):
    p = load(a['project']); t = next((t for t in p['tracks'] if t['id'] == a.get('track')), p['tracks'][0])
    lay_lyrics(t['notes'], a['lyrics']); save(a['project'], p)
    return summary(a['project'], p)


def t_set(a):
    """Track settings: voice, mode, mode_strength, gain_db, pan, transpose, expr, correct."""
    p = load(a['project']); t = next((t for t in p['tracks'] if t['id'] == a.get('track')), p['tracks'][0])
    for k in ('voice', 'mode', 'mode_strength', 'gain_db', 'pan', 'transpose', 'name', 'lang'):
        if k in a: t[k] = a[k]
    for k in ('expr', 'correct', 'steps'):
        if k in a: t['params'][k] = a[k]
    save(a['project'], p); return summary(a['project'], p)


def t_render(a):
    p = load(a['project'])
    out = render_wav(a['project'], p, a.get('out') or HOME / 'out' / f'{a["project"]}.wav', a.get('include_backing', False))
    return f'wrote {out}'


def t_check(a): return check_text(load(a['project']), a.get('track'))


def t_export(a):
    p = load(a['project']); fmt = a['format']
    data = call('POST', '/export', {'project': p, 'format': fmt})
    out = Path(a['out']).expanduser(); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data if isinstance(data, bytes) else json.dumps(data, indent=1).encode())
    return f'wrote {out}'


def t_train(a):
    name = a.get('name', 'you')
    if a.get('start'): call('POST', f'/train/start?name={name}', {'smoke': bool(a.get('smoke'))})
    s = call('GET', f'/train/status?name={name}')
    return (f'voice "{name}": {s["minutes"]} min recorded ({s["kept"]} of {s["lines"]} lines), need {s["min_minutes"]}; '
            f'{"training" if s["running"] else "idle"}; stages done: {", ".join(s["state"]) or "none"}'
            f'{"; voice ready" if s["voice"] else ""}\n{s["log"][-600:]}')


def t_tune(a):
    """Pitch-correct a sung WAV onto a MIDI part or a key (never moves the octave)."""
    wav = Path(a['wav']).expanduser()
    up = call('POST', f'/tune/upload?filename={wav.name.replace(" ", "%20")}', wav.read_bytes(), raw=True)
    body = {'wav': up['file'], 'amount': a.get('amount', 1.0), 'speed': a.get('speed', 20), 'vibrato': a.get('vibrato', False),
            'offset_ms': a.get('offset_ms', 0)}
    if a.get('midi'):
        mid = Path(a['midi']).expanduser()
        body['notes'] = call('POST', f'/tune/upload?filename={mid.name.replace(" ", "%20")}', mid.read_bytes(), raw=True)['notes']
    elif a.get('key'):
        names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        root, _, scale = a['key'].partition(' ')
        body['key'] = {'root': names.index(root.upper().replace('B', 'A#') if len(root) == 2 and root[1] == 'b' else root.upper()), 'scale': scale or 'major'}
    else: raise ValueError('give midi (a .mid of the part) or key (e.g. "A minor")')
    r = call('POST', '/tune', body)
    data = call('GET', r['url'].replace('/api/singer', ''))
    out = Path(a.get('out') or wav.with_name(wav.stem + ' (tuned).wav')).expanduser(); out.write_bytes(data)
    rows = r.get('notes') or []
    if rows:
        import statistics
        b = statistics.median(abs(x['cents_before']) for x in rows); af = statistics.median(abs(x['cents_after']) for x in rows)
        return f'wrote {out}: {len(rows)} notes, typically {b:.0f} cents off before, {af:.0f} after'
    return f'wrote {out}'


def t_bridge(a):
    """Render a project, then convert it into your voice (the bridge, until your own voice is trained)."""
    st = call('GET', '/bridge')
    if not st.get('available'): raise RuntimeError('no voice converter set up (robovox s2s.py)')
    call('POST', '/bridge', {'project': load(a['project']), 'transpose': a.get('transpose', -12)})
    t0 = time.time()
    while time.time() - t0 < 1800:
        st = call('GET', '/bridge')
        if st['state'] == 'done':
            out = Path(a.get('out') or HOME / 'out' / f'{a["project"]} (my voice).wav').expanduser(); out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(call('GET', st['url'].replace('/api/singer', ''))); return f'wrote {out} (in the voice of {Path(st["voice"]).name})'
        if st['state'] == 'failed': raise RuntimeError(st['error'])
        time.sleep(3)
    raise RuntimeError('the conversion took more than 30 minutes')


P = {'project': {'type': 'string', 'description': 'Project name (as saved in ~/MortiflixSinger/projects)'}}
TOOLS = [
    ('voices', t_voices, 'Installed voices (range, license), downloadable voices and vocoders, vocal modes.', {}),
    ('sing', t_sing, 'Sing a melody: notes as [beat, beats, midi] (beat 0 = bar 1) and one lyric token per note. Saves a '
                     'project, writes a WAV and (by default) checks every word and note. ' + LYRICS,
     {'notes': {'type': 'array', 'items': {'type': 'array', 'items': NUM}}, 'lyrics': STR, 'bpm': NUM, 'voice': STR,
      'mode': STR, 'title': STR, 'project': STR, 'out': {'type': 'string', 'description': 'WAV path (default ~/MortiflixSinger/out/<project>.wav)'},
      'check': BOOL}, ['notes', 'lyrics']),
    ('import_file', t_import, 'Import MIDI (with or without lyric events), UST, SVP, VSQX or MusicXML into a project; '
                              'optionally lay a lyrics line on the first (or given) track.',
     {'path': STR, 'project': STR, 'voice': STR, 'lyrics': STR, 'track': STR}, ['path']),
    ('projects', t_projects, 'Saved projects, newest first.', {}),
    ('show_project', t_show, 'A project: tempo, tracks, voices and each track\'s lyric line.', P, ['project']),
    ('set_lyrics', t_lyrics, 'Replace a track\'s words (one token per note). ' + LYRICS, {**P, 'lyrics': STR, 'track': STR}, ['project', 'lyrics']),
    ('set_track', t_set, 'Change a track: voice, mode (Default/Soft/Chest/Belt/Whisper/Robot), mode_strength (0-2), '
                         'gain_db, pan (-1..1), transpose (semitones), lang (en, la, es, it), expr (0 robot .. 1 natural), correct (pitch centring 0..1).',
     {**P, 'track': STR, 'voice': STR, 'mode': STR, 'mode_strength': NUM, 'gain_db': NUM, 'pan': NUM, 'transpose': INT,
      'expr': NUM, 'correct': NUM, 'name': STR, 'lang': STR}, ['project']),
    ('render', t_render, 'Render a project to a WAV (vocals; include_backing adds its backing track).',
     {**P, 'out': STR, 'include_backing': BOOL}, ['project']),
    ('check', t_check, 'Hear every word back (Whisper, phrase by phrase) and measure every note: lists unclear words and '
                       'notes more than 20 cents off, with note ids.', {**P, 'track': STR}, ['project']),
    ('export', t_export, 'Export a project as mid (with lyric events), musicxml, or msing.',
     {**P, 'format': {'type': 'string', 'enum': ['mid', 'musicxml', 'msing']}, 'out': STR}, ['project', 'format', 'out']),
    ('tune', t_tune, 'Pitch-correct any sung WAV onto its MIDI part (midi) or a key (key, e.g. "A minor"); amount 0-1, speed ms '
                     '(0 = hard snap, 20 = natural), vibrato true keeps the wobble. Never moves the octave.',
     {'wav': STR, 'midi': STR, 'key': STR, 'amount': NUM, 'speed': NUM, 'vibrato': BOOL, 'offset_ms': NUM, 'out': STR}, ['wav']),
    ('bridge', t_bridge, 'Render a project and convert it into your own voice (SoulX voice conversion; for demos, the words '
                         'get a little smudged). transpose: semitones, default -12 for a low voice.',
     {**P, 'transpose': INT, 'out': STR}, ['project']),
    ('training', t_train, 'Voice training status (recorded minutes, stages, log); start=true starts it.',
     {'name': STR, 'start': BOOL, 'smoke': BOOL}),
]


def schema(props, req=None):
    return {'type': 'object', 'properties': props, **({'required': req} if req else {})}


def main():
    by = {t[0]: t for t in TOOLS}
    for line in sys.stdin:
        if not line.strip(): continue
        msg = json.loads(line); mid = msg.get('id'); m = msg.get('method')
        if m == 'initialize':
            res = {'protocolVersion': msg['params'].get('protocolVersion', '2025-06-18'), 'capabilities': {'tools': {}},
                   'serverInfo': {'name': 'singer', 'version': '0.1.0'}}
        elif m == 'tools/list':
            res = {'tools': [{'name': n, 'description': d, 'inputSchema': schema(*rest)} for n, _, d, *rest in TOOLS]}
        elif m == 'tools/call':
            name = msg['params']['name']; args = msg['params'].get('arguments') or {}
            try: res = {'content': [{'type': 'text', 'text': by[name][1](args)}]}
            except Exception as e: res = {'content': [{'type': 'text', 'text': f'error: {e}'}], 'isError': True}
        elif mid is None:
            continue                            # notifications
        else:
            res = None
        out = {'jsonrpc': '2.0', 'id': mid, **({'result': res} if res is not None else {'error': {'code': -32601, 'message': f'no method {m}'}})}
        sys.stdout.write(json.dumps(out) + '\n'); sys.stdout.flush()


if __name__ == '__main__':
    main()
