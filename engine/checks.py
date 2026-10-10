"""Checks run on a rendered track: tuning (per note, from the sung pitch) and diction (Whisper hears each phrase on its
own, no lyrics given, and every expected word is looked for letter by letter). Each finding names the note it is on,
so the editor can jump to it."""
from __future__ import annotations
import difflib, re
import numpy as np
from .project import TempoMap

_whisper = None
norm = lambda w: re.sub(r"[^a-z]", '', w.lower())


def hear(path):
    global _whisper
    import soundfile as sf
    from scipy.signal import resample_poly
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel('small', device='cpu', compute_type='int8')
    y, sr = sf.read(path, dtype='float32')
    y = y.mean(1) if y.ndim > 1 else y
    segs, _ = _whisper.transcribe(resample_poly(y, 16000, sr).astype(np.float32), language='en', beam_size=5,
                                  condition_on_previous_text=False, without_timestamps=True)
    return ' '.join(s.text for s in segs).strip()


def words_of_track(project, track):
    """The sung words in order: [(word, [note ids])], joining "sun-" + "rise" and skipping holds and silences."""
    out, cur = [], None
    for n in sorted(track['notes'], key=lambda n: n['tick']):
        ly = (n.get('lyric') or '').strip()
        if ly in ('_', '+', '.', 'br', ''): cur = None if ly == '.' else cur; continue
        text = re.sub(r'\{.*?\}', '', ly)
        if cur is not None: cur[0] += text.rstrip('-'); cur[1].append(n['id'])
        else: cur = [text.rstrip('-'), [n['id']]]; out.append(cur)
        if not text.endswith('-'): cur = None
    return out


def check_track(project, track, phrases, diction=True, match=0.65):
    tm = TempoMap(project)
    by_id = {n['id']: n for n in track['notes']}
    tuning, words_out = [], []
    for ph in phrases:
        curve = np.array(ph.get('pitch') or [[0, 0]], float)
        for nid in ph.get('note_ids', []):
            n = by_id.get(nid)
            if not n or (n.get('lyric') or '') in ('.',): continue
            a, b = tm.to_ms(n['tick']), tm.to_ms(n['tick'] + n['dur'])
            m0, m1 = a + 0.2 * (b - a), a + 0.8 * (b - a)
            sel = curve[(curve[:, 0] >= m0) & (curve[:, 0] <= m1), 1]
            if len(sel) < 2: continue
            cents = float(np.median(sel) - (n['pitch'] + track.get('transpose', 0))) * 100
            if abs(cents) > 20: tuning.append({'note': nid, 'cents': round(cents)})
        if not diction or not ph.get('file'): continue
        ids = set(ph.get('note_ids', []))
        want = [w for w in words_of_track(project, track) if ids & set(w[1])]
        heard = hear(ph['file'])
        W = ''.join(norm(w) for w, _ in want); H = norm(heard)
        hit = np.zeros(len(W), bool)
        for blk in difflib.SequenceMatcher(a=W, b=H, autojunk=False).get_matching_blocks(): hit[blk.a:blk.a + blk.size] = True
        k = 0
        for w, nids in want:
            L = len(norm(w)); score = float(hit[k:k + L].mean()) if L else 1.0; k += L
            words_out.append({'word': w, 'notes': nids, 'ok': score >= match, 'score': round(score, 2), 'heard': heard})
    return {'tuning': tuning, 'words': words_out,
            'summary': {'words': len(words_out), 'unclear': sum(not w['ok'] for w in words_out), 'off_notes': len(tuning)}}
