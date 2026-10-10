"""The vocal pitch corrector (design doc section 9B): any vocal WAV onto MIDI notes or a key, as gently or as hard
as you choose, without the chipmunk effect.

WORLD splits the voice into pitch, spectral envelope and aperiodicity; only the pitch is changed and the voice is
rebuilt with the same envelope (formants stay put). For each sung stretch the target is the note under it (MIDI) or
the nearest note of the scale (key). The correction follows the slow part of the error, so:
  amount  0..1     how far toward the target (1 = all the way)
  speed   0..200   ms the correction takes to follow (0 = hard snap)
  vibrato True     the fast wobble around the centre is kept; only the centre moves
"""
from __future__ import annotations
import numpy as np

FRAME_MS = 5.0
SCALES = {'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10], 'dorian': [0, 2, 3, 5, 7, 9, 10],
          'mixolydian': [0, 2, 4, 5, 7, 9, 10], 'harmonic minor': [0, 2, 3, 5, 7, 8, 11], 'pentatonic major': [0, 2, 4, 7, 9],
          'pentatonic minor': [0, 3, 5, 7, 10], 'blues': [0, 3, 5, 6, 7, 10], 'chromatic': list(range(12))}


def smooth(x, frames):
    if frames <= 1: return x.copy()
    k = np.ones(int(frames)) / int(frames)
    return np.convolve(np.pad(x, (int(frames) // 2, int(frames) - int(frames) // 2 - 1), mode='edge'), k, 'valid')


def analyse(y, sr):
    import pyworld as pw
    x = y.astype(np.float64)
    f0, t = pw.harvest(x, sr, frame_period=FRAME_MS, f0_floor=55, f0_ceil=1100)
    sp = pw.cheaptrick(x, f0, t, sr); ap = pw.d4c(x, f0, t, sr)
    return f0, t, sp, ap


def segments(voiced):
    """(start, end) frame ranges of continuous voiced sound."""
    out, a = [], None
    for i, v in enumerate(np.append(voiced, False)):
        if v and a is None: a = i
        elif not v and a is not None: out.append((a, i)); a = None
    return out


def targets(midi, t_ms, notes=None, key=None):
    """Per frame: the pitch to aim for (NaN = leave alone)."""
    tgt = np.full(len(midi), np.nan)
    voiced = ~np.isnan(midi)
    if notes:
        for s, d, m in notes:
            sel = (t_ms >= s) & (t_ms < s + d) & voiced
            if not sel.any(): continue
            # the written note in whichever octave was sung: tuning is fixed, the octave never moved (no chipmunks)
            tgt[sel] = m + 12 * np.round((np.median(midi[sel]) - m) / 12)
        return tgt
    root, scale = key
    allowed = np.array([root % 12 + i + 12 * o for o in range(-1, 11) for i in SCALES.get(scale, SCALES['major'])], float)
    for a, b in segments(voiced):                   # each sung stretch: notes by its steady parts (100 ms median)
        seg = midi[a:b]
        med = np.array([np.median(seg[max(0, i - 10):i + 10]) for i in range(len(seg))])
        tgt[a:b] = allowed[np.abs(allowed[None, :] - med[:, None]).argmin(1)]
    return tgt


def correct(y, sr, notes=None, key=None, amount=1.0, speed=60.0, vibrato=True):
    """-> (corrected audio, report). notes: [(start_ms, dur_ms, midi)]; key: (root 0-11, scale name)."""
    import pyworld as pw
    if not notes and not key: raise ValueError('give MIDI notes or a key')
    f0, t, sp, ap = analyse(y, sr)
    t_ms = t * 1000
    midi = np.where(f0 > 0, 69 + 12 * np.log2(np.maximum(f0, 1e-6) / 440), np.nan)
    tgt = targets(midi, t_ms, notes, key)
    err = tgt - midi                                  # semitones to move each frame (NaN where nothing to do)
    err[np.abs(err) > 3] = np.nan                     # slides, ornaments and tracker glitches far from the note: left alone
    have = ~np.isnan(err)
    shift = np.zeros(len(midi))
    # each run of one target (a note, or a scale step) is corrected on its own, so a note's correction never leaks
    # into its neighbour in legato singing; the joins are then eased over the speed setting
    runs, a = [], None
    for i in range(len(tgt) + 1):
        if i < len(tgt) and have[i] and a is not None and tgt[i] == tgt[a]: continue
        if a is not None: runs.append((a, i))
        a = i if i < len(tgt) and have[i] else None
    for a, b in runs:
        e = err[a:b]
        if vibrato:
            # one steady shift per note (its median error) keeps the vibrato exactly; long notes also follow slow
            # drift, averaged over 250 ms (longer than a vibrato cycle, so the wobble itself is left alone)
            centre = np.full(len(e), np.median(e))
            if len(e) * FRAME_MS > 600: centre = smooth(e, 250 / FRAME_MS)
        else:
            w = max(1, speed / FRAME_MS)
            centre = smooth(e, min(w, len(e))) if w > 1 else e
        shift[a:b] = amount * centre
    shift = smooth(shift, max(3, speed / FRAME_MS / 2))     # ease the joins (no clicks)
    new_midi = np.where(have, midi + shift, midi)
    f0_new = np.where(f0 > 0, 440 * 2 ** ((np.nan_to_num(new_midi, nan=69) - 69) / 12), 0)
    out = pw.synthesize(f0_new, sp, ap, sr, frame_period=FRAME_MS).astype(np.float32)
    out = out[:len(y)] if len(out) >= len(y) else np.pad(out, (0, len(y) - len(out)))
    report = {'frame_ms': FRAME_MS,
              'before': [[round(float(a), 1), None if np.isnan(m) else round(float(m), 3)] for a, m in zip(t_ms[::2], midi[::2])],
              'after': [[round(float(a), 1), None if np.isnan(m) else round(float(m), 3)] for a, m in zip(t_ms[::2], new_midi[::2])]}
    if notes:
        rows = []
        for s, d, m in notes:
            sel = (t_ms >= s + 0.2 * d) & (t_ms < s + 0.8 * d) & have      # the note itself (not slides into it)
            if sel.sum() < 3: continue
            oct_ = 12 * np.round((np.median(midi[sel]) - m) / 12)          # measured against the octave sung
            rows.append({'start': s, 'dur': d, 'midi': m, 'octave': int(oct_ // 12), 'cents_before': round(float(np.median(midi[sel]) - m - oct_) * 100),
                         'cents_after': round(float(np.median(new_midi[sel]) - m - oct_) * 100)})
        report['notes'] = rows
    return out, report
