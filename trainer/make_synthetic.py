#!/usr/bin/env python3
"""A labelled test dataset without a singer: the bridge voice sings the Booth's balanced lines, and because our engine
places every phoneme itself, the exact labels (phonemes, their lengths, notes) are known. Used to prove the training
pipeline end to end and to measure the aligner against the truth before anyone records.

  make_synthetic.py --out datasets/synthetic --lines 60 [--transpose 12]
Writes OUT/wavs/*.wav (44.1 kHz mono) and OUT/transcriptions.csv (DiffSinger's format)."""
import argparse, csv, json, sys
from pathlib import Path
import numpy as np, soundfile as sf

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from engine.ds import Voice, Word, Note, VOWELS, HEAD
from engine.song import phonemes

NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
name = lambda m: f'{NAMES[int(m) % 12]}{int(m) // 12 - 1}'


def line_words(line, voice, transpose):
    """The script line's words laid on its melody: each word gets as many notes as it has vowels."""
    bpm = line['melody']['bpm']; spb = 60000 / bpm
    notes = [Note(1000 + n['beat'] * spb, n['beats'] * spb * 0.97, n['midi'] + transpose, '') for n in line['melody']['notes']]
    words, k = [], 0
    for w in line['text'].replace('-', ' ').split():
        ph = phonemes(w, voice.tokens)
        nv = max(1, sum(p in VOWELS for p in ph))
        if not ph or k >= len(notes): continue
        take = notes[k:k + nv] or [notes[-1]]
        words.append(Word(list(take), ph)); k += nv
    if words:                                         # an in-breath before the line, as a singer takes one
        first = words[0].notes[0]
        words.insert(0, Word([Note(first.start - 480, 400, first.midi, 'br')], ['AP']))
    return words


def labels(phones, t0, total_s, words):
    """DiffSinger transcription columns from the engine's phone layout, times relative to the clip start."""
    seq, dur = ['SP'], [phones[0][1] - t0]
    for p, s, e in phones: seq.append(p); dur.append(e - s)
    seq.append('SP'); dur.append(max(10.0, total_s * 1000 - (phones[-1][2] - t0)))
    # words begin at vowels (the onset consonants belong to the word before), the leading SP + consonants first
    num, cur = [], 0
    for i, p in enumerate(seq):
        starts = p in VOWELS and i > 0
        if starts and cur: num.append(cur); cur = 0
        cur += 1
    # the final SP is its own word
    if cur > 1: num.extend([cur - 1, 1])
    else: num.append(cur)
    notes_seq, notes_dur, k, idx = [], [], 0, 0
    sung = [n for w in words if w.phonemes != ['AP'] for n in w.notes]      # breaths have no note
    for g in num:
        group = seq[idx:idx + g]; gd = sum(dur[idx:idx + g]) / 1000
        if any(p in VOWELS for p in group) and k < len(sung): notes_seq.append(name(round(sung[k].midi))); k += 1
        else: notes_seq.append('rest')
        notes_dur.append(gd); idx += g
    return seq, [d / 1000 for d in dur], num, notes_seq, notes_dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True); ap.add_argument('--lines', type=int, default=60); ap.add_argument('--transpose', type=int, default=12)
    ap.add_argument('--voice', default=str(HERE.parent / 'voices/SPORE/SPORE')); ap.add_argument('--vocoder', default=str(HERE.parent / 'voices/nsf_hifigan'))
    a = ap.parse_args()
    out = Path(a.out); (out / 'wavs').mkdir(parents=True, exist_ok=True)
    v = Voice(a.voice, a.vocoder)
    script = json.loads((HERE.parent / 'booth/script.json').read_text())
    lines = [r for r in script if r['set'] == 'C'][:a.lines]
    rows = []
    for i, line in enumerate(lines):
        words = line_words(line, v, a.transpose)
        if not words: continue
        wav, t0, c = v.render_phrase(words, steps=20, seed=i)
        sf.write(out / 'wavs' / f"{line['id']}.wav", wav, v.sr)
        seq, dur, num, nseq, ndur = labels(c['phones'], t0, len(wav) / v.sr, words)
        rows.append({'name': line['id'], 'ph_seq': ' '.join(seq), 'ph_dur': ' '.join(f'{d:.5f}' for d in dur),
                     'ph_num': ' '.join(map(str, num)), 'note_seq': ' '.join(nseq), 'note_dur': ' '.join(f'{d:.5f}' for d in ndur)})
        print(f"{line['id']}: {len(seq)} phonemes, {sum(dur):.2f} s", flush=True)
    with open(out / 'transcriptions.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f'{len(rows)} lines -> {out}')


if __name__ == '__main__':
    main()
