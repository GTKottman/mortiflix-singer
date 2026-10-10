#!/usr/bin/env python3
"""Booth takes -> a DiffSinger training dataset (wavs/ + transcriptions.csv).

  build_dataset.py --booth ~/MortiflixSinger/datasets/you --out ~/MortiflixSinger/train/you
  build_dataset.py --list takes.csv --out ...          (rows: wav, text, preroll_s) for recordings made elsewhere

For every kept take: cut the pre-roll, resample to 44.1 kHz mono, turn the line into phonemes, align them (align.py),
and label the notes from what was actually sung (tone-deaf first: a note is the sung pitch rounded to a semitone, never
the guide). Takes the aligner can't place are listed and left out. Writes report.json with what was kept and why not."""
import argparse, csv, json, sys
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import resample_poly

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
from engine.song import phonemes
from engine.ds import VOWELS

TOKENS = {p: 1 for p in 'aa ae ah ao aw ax ay b ch d dh eh er ey f g hh ih iy jh k l m n ng ow oy p r s sh t th uh uw v w y z zh'.split()}
NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
SPECIAL = {'ah (hold)': ['aa'], 'ee (hold)': ['iy'], 'oo (hold)': ['uw'], 'eh (hold)': ['eh'], 'oh (hold)': ['ow'],
           'a (cat) (hold)': ['ae'], 'uh (hold)': ['ah'], 'eye (hold)': ['ay'], 'hum': ['m'], 'ooh': ['uw'], 'ah': ['aa'], 'in-breath': None}
SR = 44100


def line_phonemes(text):
    t = text.strip().lower()
    for k, v in SPECIAL.items():
        if t == k or t.startswith(k.split(' (')[0] + ' (with') or t.startswith(k.split(' (')[0] + ' (straight'): return v
    out = []
    for w in t.replace('-', ' ').split(): out += phonemes(w, TOKENS)
    return out


def sung_notes(y, sr, spans):
    """For each vowel-led group, the sung pitch (median of its vowel), rounded: what you sang is the label."""
    import pyworld as pw
    f0, t = pw.harvest(y.astype(np.float64), sr, frame_period=10.0, f0_floor=55, f0_ceil=900)
    out = []
    for a, b in spans:
        v = f0[(t >= a) & (t < b) & (f0 > 0)]
        out.append(None if len(v) < 3 else int(round(69 + 12 * np.log2(np.median(v) / 440))))
    return out


def find_breath(y, sr, a, b):
    """An audible in-breath between a and b seconds: the longest run (>= 150 ms) of unvoiced sound well above the
    clip's noise floor. -> (start, end) or None."""
    import pyworld as pw
    hop = int(sr * 0.01)
    seg = y[int(a * sr):int(b * sr)]
    if len(seg) < hop * 15: return None
    rms = lambda x: 20 * np.log10(np.sqrt(np.mean(x.reshape(-1, hop) ** 2, 1)) + 1e-9)
    whole = rms(y[:len(y) // hop * hop]); floor = np.percentile(whole, 10)
    r = rms(seg[:len(seg) // hop * hop])
    f0, _ = pw.harvest(seg.astype(np.float64), sr, frame_period=10.0, f0_floor=55, f0_ceil=900)
    loud = (r > floor + 12) & (f0[:len(r)] == 0)
    best, run, start = None, 0, 0
    for i, v in enumerate(np.append(loud, False)):
        if v:
            if not run: start = i
            run += 1
        else:
            if run >= 15 and (best is None or run > best[1] - best[0]): best = (start, start + run)
            run = 0
    return None if best is None else (a + best[0] * 0.01, a + best[1] * 0.01)


def rows_for(name, y, sr, phones, aligner, preroll=0.0):
    y = y[int(preroll * sr):]
    y = resample_poly(y, SR, sr).astype(np.float32) if sr != SR else y.astype(np.float32)
    total = len(y) / SR
    if not phones:                                                     # an in-breath line: the breath is the take
        br = find_breath(y, SR, 0, total)
        if br is None: raise RuntimeError('no breath heard')
        seq, dur = ['SP', 'AP', 'SP'], [max(0.01, br[0]), br[1] - br[0], max(0.01, total - br[1])]
        return y, {'name': name, 'ph_seq': ' '.join(seq), 'ph_dur': ' '.join(f'{d:.5f}' for d in dur), 'ph_num': '3',
                   'note_seq': 'rest', 'note_dur': f'{sum(dur):.5f}'}
    al = aligner.align(y, SR, phones)
    br = find_breath(y, SR, 0, al[0][1] - 0.02)                        # the breath singers take before the line
    if br: seq, dur = ['SP', 'AP'], [max(0.01, br[0]), max(0.01, al[0][1] - br[0])]
    else: seq, dur = ['SP'], [max(0.01, al[0][1])]
    for i, (p, s, e) in enumerate(al):
        nxt = al[i + 1][1] if i + 1 < len(al) else min(total, e + 0.25)
        seq.append(p); dur.append(max(0.01, nxt - s))
    seq.append('SP'); dur.append(max(0.01, total - sum(dur)))
    # words begin at vowels; the leading SP and onset consonants are the first word, the final SP the last
    num, cur = [], 0
    for i, p in enumerate(seq[:-1]):
        if p in VOWELS and cur: num.append(cur); cur = 0
        cur += 1
    num += [cur, 1]
    starts = np.concatenate([[0], np.cumsum(dur)])
    spans, idx = [], 0
    for g in num:
        vow = [k for k in range(idx, idx + g) if seq[k] in VOWELS]
        spans.append((starts[vow[0]], starts[vow[0] + 1]) if vow else None); idx += g
    pitches = sung_notes(y, SR, [s for s in spans if s])
    notes, k = [], 0
    for s in spans:
        if s is None: notes.append('rest'); continue
        m = pitches[k]; k += 1
        notes.append('rest' if m is None else f'{NAMES[m % 12]}{m // 12 - 1}')
    note_dur, idx = [], 0
    for g in num: note_dur.append(sum(dur[idx:idx + g])); idx += g
    return y, {'name': name, 'ph_seq': ' '.join(seq), 'ph_dur': ' '.join(f'{d:.5f}' for d in dur), 'ph_num': ' '.join(map(str, num)),
               'note_seq': ' '.join(notes), 'note_dur': ' '.join(f'{d:.5f}' for d in note_dur)}


def takes_from_booth(booth_dir):
    b = json.loads((Path(booth_dir) / 'booth.json').read_text())
    script = {r['id']: r for r in json.loads((HERE.parent / 'booth/script.json').read_text())}
    for lid, k in b['kept'].items():
        take = next((t for t in b['takes'][lid] if t['take'] == k), None)
        yield {'name': f'{lid}_{k}', 'wav': Path(booth_dir) / 'raw' / f'{lid}_{k}.wav', 'text': script[lid]['text'], 'preroll': (take or {}).get('preroll', 0.5)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--booth'); ap.add_argument('--list'); ap.add_argument('--out', required=True); ap.add_argument('--device', default='cpu')
    a = ap.parse_args()
    from align import Aligner
    aligner = Aligner(device=a.device)
    out = Path(a.out); (out / 'wavs').mkdir(parents=True, exist_ok=True)
    takes = list(takes_from_booth(a.booth)) if a.booth else [{'name': Path(r['wav']).stem, 'wav': Path(r['wav']), 'text': r['text'], 'preroll': float(r.get('preroll_s') or 0)} for r in csv.DictReader(open(a.list))]
    rows, skipped = [], []
    for t in takes:
        phones = line_phonemes(t['text'])
        if phones is None: phones = []                                  # in-breath line
        try:
            y, sr = sf.read(t['wav'], dtype='float32', always_2d=True)
            y2, row = rows_for(t['name'], y.mean(1), sr, phones, aligner, t['preroll'])
            sf.write(out / 'wavs' / f"{t['name']}.wav", y2, SR, subtype='PCM_16')
            rows.append(row)
        except Exception as e:
            skipped.append({'name': t['name'], 'why': str(e)})
    if rows:
        with open(out / 'transcriptions.csv', 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    minutes = sum(sf.info(out / 'wavs' / f"{r['name']}.wav").duration for r in rows) / 60
    (out / 'report.json').write_text(json.dumps({'kept': len(rows), 'minutes': round(minutes, 1), 'skipped': skipped}, indent=1))
    print(f'{len(rows)} takes ({minutes:.1f} min) -> {out}; {len(skipped)} left out')


if __name__ == '__main__':
    main()
