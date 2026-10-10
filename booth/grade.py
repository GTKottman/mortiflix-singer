"""Grades one Booth take in about a second: level, noise, words, steadiness, timing. Tone-deaf first: how close the
take was to the guide melody is reported for interest only and never lowers the grade (the dataset is labelled from
what was actually sung)."""
from __future__ import annotations
import difflib, re
import numpy as np
from scipy.signal import resample_poly

_whisper = None
norm = lambda s: re.sub(r'[^a-z]', '', s.lower())
NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def db(x): return 20 * np.log10(max(float(x), 1e-9))


def words_heard(y16):
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel('small', device='cpu', compute_type='int8')
    segs, _ = _whisper.transcribe(y16, language='en', beam_size=3, condition_on_previous_text=False, without_timestamps=True)
    return ' '.join(s.text for s in segs).strip()


def pitch_track(y, sr):
    import pyworld as pw
    f0, t = pw.harvest(y.astype(np.float64), sr, frame_period=10.0, f0_floor=55, f0_ceil=800)
    return f0, t


def grade(y: np.ndarray, sr: int, line: dict, bpm: float | None = None, preroll_s: float = 0.0) -> dict:
    """y = the take; its first `preroll_s` seconds are the silence before the downbeat (where the room noise is measured)."""
    y = y.mean(1) if y.ndim > 1 else y
    out = {'problems': [], 'notes': []}
    peak = db(np.abs(y).max())
    clipped = int((np.abs(y) > 0.999).sum())
    pre = y[:int(preroll_s * sr)]
    floor = db(np.sqrt(np.mean(pre ** 2))) if len(pre) > sr // 20 else None
    y = y[int(preroll_s * sr):]
    out.update(peak_db=round(peak, 1), noise_db=None if floor is None else round(floor, 1), clipped=clipped)
    if clipped > 10: out['problems'].append('clipped: turn the input down a little')
    if peak < -30: out['problems'].append('too quiet: move closer or turn the input up')
    if floor is not None and floor > -45: out['problems'].append(f'noisy room ({floor:.0f} dB): find the noise or add blankets')

    f0, t = pitch_track(resample_poly(y, 16000, sr) if sr != 16000 else y, 16000)
    voiced = f0 > 0
    if voiced.sum() < 10:
        out['problems'].append('no singing heard'); out['grade'] = 'C'; return out
    semis = 69 + 12 * np.log2(np.where(voiced, f0, 1) / 440)
    # steadiness: how far each voiced frame strays from its own 150 ms neighbourhood (vibrato is fine, drifting isn't)
    k = 7
    med = np.array([np.median(semis[max(0, i - k):i + k + 1][voiced[max(0, i - k):i + k + 1]]) if voiced[i] else 0 for i in range(len(semis))])
    stray = np.abs(semis - med)[voiced]
    wobble = float((stray > 0.75).mean())
    held = len(line.get('melody', {}).get('notes', [])) == 1          # one held note: it should not drift at all
    if held:
        smooth = med[voiced][len(med[voiced]) // 10: -len(med[voiced]) // 10 or None]
        if len(smooth) > 10 and np.percentile(smooth, 90) - np.percentile(smooth, 10) > 1.0: wobble = max(wobble, 0.5)
    out['wobble'] = round(wobble, 2)
    if wobble > 0.25: out['problems'].append('a note wobbled: hold each note steady (being sharp or flat is fine)')
    # what you sang, as notes (the dataset's labels) and, for interest only, against the guide
    sung = []
    cur, start = None, 0
    for i, (v, s) in enumerate(zip(voiced, semis)):
        n = int(round(s)) if v else None
        if n != cur:
            if cur is not None and i - start >= 8: sung.append((cur, start / 100, (i - start) / 100))
            cur, start = n, i
    if cur is not None and len(semis) - start >= 8: sung.append((cur, start / 100, (len(semis) - start) / 100))
    out['notes'] = [{'midi': n, 'name': f'{NAMES[n % 12]}{n // 12 - 1}', 'start': round(s, 2), 'dur': round(d, 2)} for n, s, d in sung]
    guide = [n['midi'] for n in line.get('melody', {}).get('notes', [])]
    if guide and sung:
        off = int(np.median([n for n, _, _ in sung])) - int(np.median(guide))
        out['key_offset'] = off               # the follow-me shift you landed on: information, not a grade
    # timing: the first sound should start within a beat of the downbeat
    beat = 60 / (bpm or line.get('melody', {}).get('bpm', 90))
    onset = float(t[np.argmax(voiced)]) if voiced.any() else 0
    out['onset_s'] = round(onset, 2)
    if onset > beat * 1.5: out['problems'].append('started late: come in on the downbeat')
    # words (not for held vowels, scales, holds, breaths)
    if line.get('set') in ('C', 'D', 'E') and line.get('text'):
        heard = words_heard((resample_poly(y, 16000, sr) if sr != 16000 else y).astype(np.float32))
        want = norm(line['text'])
        sm = difflib.SequenceMatcher(a=want, b=norm(heard), autojunk=False)
        match = sum(b.size for b in sm.get_matching_blocks()) / max(1, len(want))
        out.update(heard=heard, words=round(match, 2))
        if match < 0.6: out['problems'].append(f'words unclear (heard "{heard}")')
    hard = [p for p in out['problems'] if not p.startswith('noisy')]
    out['grade'] = 'C' if hard else ('B' if out['problems'] or out.get('words', 1) < 0.8 else 'A')
    return out
