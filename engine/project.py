"""Projects (.msing, JSON): tracks of notes with words, lanes and vocal modes; rendered phrase by phrase with a cache,
so an edit re-renders only the phrases it touched.

{ "version": 1, "ppq": 480, "tempo": [{"tick": 0, "bpm": 120}], "time_sig": [4, 4], "title": "...",
  "tracks": [{ "id": "t1", "name": "Lead", "voice": "SPORE", "mode": "Default", "mute": false, "solo": false,
               "gain_db": 0, "pan": 0, "transpose": 0,
               "notes": [{"id": "n1", "tick": 0, "dur": 480, "pitch": 60, "lyric": "la", "vel": 64,
                          "vib_depth": 0, "vib_rate": 5.5, "vib_start": 250, "phonemes": null, "lock": false}],
               "lanes": {"pitch": [[tick, cents], ...], "energy": [...], "breathiness": [...], "voicing": [...],
                         "tension": [...], "gender": [...], "velocity": [...]},
               "pitch_draw": [[tick, midi], ...] or [],
               "params": {"expr": 1.0, "correct": 1.0, "steps": 20} }] }
"""
from __future__ import annotations
import hashlib, json
from bisect import bisect_right
from pathlib import Path
import numpy as np
from .ds import Voice
from . import song

MODES = {    # vocal modes: constant offsets on the expression curves (design doc section 6)
    'Default': {},
    'Soft': {'breathiness': 6, 'energy': -4, 'tension': -3},
    'Chest': {'energy': 3, 'tension': 2, 'breathiness': -6},
    'Belt': {'energy': 6, 'tension': 5, 'gender': 0.15},
    'Whisper': {'voicing': -40, 'breathiness': 12},
    'Robot': {'breathiness': -20, '_expr': 0.0},
}
LANES = ('pitch', 'energy', 'breathiness', 'voicing', 'tension', 'gender', 'velocity')


def new_project(title='Untitled', bpm=120.0):
    return {'version': 1, 'ppq': 480, 'title': title, 'tempo': [{'tick': 0, 'bpm': bpm}], 'time_sig': [4, 4],
            'tracks': [{'id': 't1', 'name': 'Lead', 'voice': 'SPORE', 'mode': 'Default', 'mute': False, 'solo': False,
                        'gain_db': 0, 'pan': 0, 'transpose': 0, 'notes': [], 'lanes': {}, 'pitch_draw': [],
                        'params': {'expr': 1.0, 'correct': 1.0, 'steps': 20}}]}


class TempoMap:
    def __init__(self, project):
        self.ppq = project.get('ppq', 480)
        pts = sorted(project.get('tempo') or [{'tick': 0, 'bpm': 120}], key=lambda p: p['tick'])
        if pts[0]['tick'] != 0: pts.insert(0, {'tick': 0, 'bpm': pts[0]['bpm']})
        self.ticks, self.bpms, self.ms = [], [], []
        acc = 0.0
        for i, p in enumerate(pts):
            if i: acc += (p['tick'] - pts[i - 1]['tick']) * 60000 / (pts[i - 1]['bpm'] * self.ppq)
            self.ticks.append(p['tick']); self.bpms.append(p['bpm']); self.ms.append(acc)

    def to_ms(self, tick):
        i = max(0, bisect_right(self.ticks, tick) - 1)
        return self.ms[i] + (tick - self.ticks[i]) * 60000 / (self.bpms[i] * self.ppq)

    def to_tick(self, ms):
        i = max(0, bisect_right(self.ms, ms) - 1)
        return self.ticks[i] + (ms - self.ms[i]) * self.bpms[i] * self.ppq / 60000


def lane_fn(points, tm: TempoMap, default=0.0):
    """Lane points [[tick, value], ...] -> f(ms array) by linear interpolation; flat outside."""
    if not points: return None
    pts = sorted(points)
    xs = np.array([tm.to_ms(t) for t, _ in pts]); ys = np.array([v for _, v in pts], float)
    return lambda ms: np.interp(ms, xs, ys)


def draw_fn(points, tm: TempoMap):
    """A drawn pitch line: segments of [tick, midi] points; NaN where nothing is drawn (the model's curve stays)."""
    if not points: return None
    pts = sorted(points)
    xs = np.array([tm.to_ms(t) for t, _ in pts]); ys = np.array([v for _, v in pts], float)

    def f(ms):
        out = np.interp(ms, xs, ys)
        gap = np.zeros_like(ms, bool)                 # breaks of more than 120 ms between drawn points are not drawn
        idx = np.searchsorted(xs, ms)
        inside = (idx > 0) & (idx < len(xs))
        gap[inside] = (xs[idx[inside]] - xs[idx[inside] - 1]) > 120
        return np.where((ms < xs[0]) | (ms > xs[-1]) | gap, np.nan, out)
    return f


def track_words(voice: Voice, project, track):
    tm = TempoMap(project)
    notes = sorted(track['notes'], key=lambda n: n['tick'])
    raw = [[tm.to_ms(n['tick']), tm.to_ms(n['tick'] + n['dur']) - tm.to_ms(n['tick']), n['pitch'] + track.get('transpose', 0)] for n in notes]
    toks = []
    for n in notes:
        lyr = (n.get('lyric') or 'la').strip() or 'la'
        if n.get('phonemes'): lyr = f"{lyr.rstrip('-')}{{{n['phonemes']}}}" + ('-' if lyr.endswith('-') else '')
        toks.append(lyr)
    words = song.words_of(raw, toks, voice.tokens, track.get('lang', 'en'))
    by_start = {round(tm.to_ms(n['tick']), 3): n for n in notes}
    for w in words:                                   # per-phoneme lengths live on the word's first note
        n0 = by_start.get(round(w.notes[0].start, 3))
        if n0 and isinstance(n0.get('ph_scale'), list) and len(n0['ph_scale']) == len(w.phonemes): w.scales = n0['ph_scale']
    for w in words:                                   # per-note settings onto the engine's notes
        for en in w.notes:
            n = by_start.get(round(en.start, 3))
            if not n: continue
            en.vib_depth = float(n.get('vib_depth') or 0); en.vib_rate = float(n.get('vib_rate') or 5.5)
            en.vib_start = float(n.get('vib_start') or 250)
            en.lead = float(n['lead']) if n.get('lead') not in (None, '') else None
            en.glide = float(n['glide']) if n.get('glide') not in (None, '') else None
            en.glide_offset = float(n.get('glide_offset') or 0)
            v = n.get('vel', 64)
            en.energy = 6 * (v - 64) / 63 if v >= 64 else 12 * (v - 64) / 63
    return words, tm


def expand_groups(project):
    """Note groups -> plain notes. A group is stored once (project['groups'][gid]['notes'], ticks from the group's
    start); tracks place it with refs [{id, group, tick, transpose}]. Each instance's notes get ids '<ref>~<note>'."""
    groups = project.get('groups') or {}
    if not groups or not any(t.get('refs') for t in project.get('tracks', [])): return project
    out = dict(project); out['tracks'] = []
    for t in project['tracks']:
        t2 = dict(t); notes = list(t.get('notes', []))
        for r in t.get('refs') or []:
            g = groups.get(r.get('group'))
            if not g: continue
            for n in g.get('notes', []):
                notes.append({**n, 'id': f"{r['id']}~{n['id']}", 'tick': n['tick'] + int(r.get('tick', 0)),
                              'pitch': n['pitch'] + int(r.get('transpose', 0))})
        t2['notes'] = notes; t2.pop('refs', None); out['tracks'].append(t2)
    out.pop('groups', None)
    return out


def phrase_key(voice_id, words, track, lanes_sig, params):
    data = {'v': voice_id, 'w': [[(n.start, n.dur, n.midi, n.lyric, n.vib_depth, n.vib_rate, n.vib_start, n.energy, n.lead, n.glide, n.glide_offset) for n in w.notes] + [w.phonemes, w.scales] for w in words],
            'mode': track.get('mode', 'Default'), 'ms': track.get('mode_strength', 1.0), 'lang': track.get('lang', 'en'), 'lanes': lanes_sig, 'p': params}
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:20]


def render_track(voice: Voice, voice_id: str, project, track, cache: Path, quality='final', on_phrase=None):
    """Render a track phrase by phrase (cached). -> list of {hash, start_ms, end_ms, file, pitch:[[ms, midi]...], phones}"""
    import soundfile as sf
    cache.mkdir(parents=True, exist_ok=True)
    words, tm = track_words(voice, project, track)
    if not words: return []
    params = dict(track.get('params') or {})
    steps = 8 if quality == 'preview' else int(params.get('steps', 20))
    mode = MODES.get(track.get('mode', 'Default'), {})
    strength = float(track.get('mode_strength', 1.0))           # 0 = off, 1 = as designed, 2 = twice as strong
    offsets = {k: v * strength for k, v in mode.items() if not k.startswith('_')}
    base_expr = params.get('expr', 1.0)
    expr = base_expr + (mode['_expr'] - base_expr) * min(strength, 1.0) if '_expr' in mode else base_expr
    lanes = {k: f for k in LANES if (f := lane_fn((track.get('lanes') or {}).get(k), tm))}
    drawn = draw_fn(track.get('pitch_draw'), tm)
    out = []
    for i, ph in enumerate(song.phrases_of(words)):
        a = ph[0].notes[0].start - 600; b = ph[-1].notes[-1].start + ph[-1].notes[-1].dur + 600
        sig = {k: [p for p in (track.get('lanes') or {}).get(k, []) if a <= tm.to_ms(p[0]) <= b] for k in LANES}
        sig['draw'] = [p for p in (track.get('pitch_draw') or []) if a <= tm.to_ms(p[0]) <= b]
        first_tick = round(tm.to_tick(ph[0].notes[0].start))
        take = int((track.get('takes') or {}).get(str(first_tick), 0))           # pitch take (a new draw of everything)
        tone = int((track.get('tone_takes') or {}).get(str(first_tick), 0))      # tone take: same pitch, new voice draw
        base = {'steps': steps, 'expr': expr, 'correct': params.get('correct', 1.0), 'take': take}
        key = phrase_key(voice_id, ph, track, sig, {**base, 'tone': tone} if tone else base)
        wav_f, meta_f = cache / f'{key}.wav', cache / f'{key}.json'
        if wav_f.exists() and meta_f.exists():
            meta = json.loads(meta_f.read_text())
        else:
            override = drawn
            if tone:           # keep the pitch take's exact curve: render (or reuse) the pitch take, then follow its pitch
                bkey = phrase_key(voice_id, ph, track, sig, base); bmeta = cache / f'{bkey}.json'
                if not bmeta.exists():
                    w0, t00, c0 = voice.render_phrase(ph, steps=steps, expr=expr, correct=params.get('correct', 1.0), seed=i,
                                                      lanes=lanes, offsets=offsets, pitch_override=drawn)
                    sf.write(cache / f'{bkey}.wav', w0, voice.sr, subtype='FLOAT')
                    fm0 = c0['frame_ms']
                    bmeta.write_text(json.dumps({'hash': bkey, 'start_ms': t00, 'end_ms': t00 + len(w0) / voice.sr * 1000,
                                                 'pitch': [[round(t00 + j * fm0, 1), round(float(m), 3)] for j, m in enumerate(c0['pitch']) if j % 2 == 0],
                                                 'phones': [[q, round(a_, 1), round(b_, 1)] for q, a_, b_ in c0['phones']]}))
                bp = np.array(json.loads(bmeta.read_text())['pitch'], float)
                override = lambda ms, bp=bp: np.interp(ms, bp[:, 0], bp[:, 1])
            wav, t0, c = voice.render_phrase(ph, steps=steps, expr=expr, correct=params.get('correct', 1.0), seed=i,
                                             lanes=lanes, offsets=offsets, pitch_override=override)
            sf.write(wav_f, wav, voice.sr, subtype='FLOAT')
            fm = c['frame_ms']
            pitch = [[round(t0 + j * fm, 1), round(float(m), 3)] for j, m in enumerate(c['pitch']) if j % 2 == 0]
            meta = {'hash': key, 'first_tick': first_tick, 'take': take, 'start_ms': t0, 'end_ms': t0 + len(wav) / voice.sr * 1000, 'pitch': pitch,
                    'phones': [[p, round(s, 1), round(e, 1)] for p, s, e in c['phones']]}
            meta_f.write_text(json.dumps(meta))
        meta['file'] = str(wav_f); meta['first_tick'] = first_tick; meta['take'] = take; meta['tone'] = tone
        meta['note_ids'] = [n['id'] for n in track['notes'] if any(abs(tm.to_ms(n['tick']) - en.start) < 0.5 for w in ph for en in w.notes)]
        out.append(meta)
        if on_phrase: on_phrase(i, meta)
    return out


def mixdown(voice_sr, project, results_by_track, tracks):
    """Every track's phrases on one timeline -> stereo float32 (gain, pan, mute, solo)."""
    import soundfile as sf
    end = max((m['end_ms'] for r in results_by_track.values() for m in r), default=0) + 500
    out = np.zeros((int(end / 1000 * voice_sr) + 1, 2), np.float32)
    soloed = any(t.get('solo') for t in tracks)
    for t in tracks:
        if t.get('mute') or (soloed and not t.get('solo')): continue
        g = 10 ** (t.get('gain_db', 0) / 20); pan = float(t.get('pan', 0))
        lr = np.array([np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)]) * np.sqrt(2)
        for m in results_by_track.get(t['id'], []):
            y, _ = sf.read(m['file'], dtype='float32')
            a = int(round(m['start_ms'] / 1000 * voice_sr))
            if a < 0: y, a = y[-a:], 0
            n = min(len(y), len(out) - a)
            k = min(441, n // 2); fade = np.ones(n, np.float32); fade[:k] = np.linspace(0, 1, k); fade[n - k:] = np.linspace(1, 0, k)
            out[a:a + n] += (y[:n] * fade * g)[:, None] * lr[None, :]
    return out
