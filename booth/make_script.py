#!/usr/bin/env python3
"""Builds the Booth's recording script: every line you sing, its set, its syllables and a guide melody in your range.

Set C (balanced lines) is chosen greedily from the CMU Arctic prompts (public-domain Project Gutenberg text), cut at
commas into singable 5-11 syllable lines, until every pair of neighbouring English sounds has been covered 3 times or
300 lines are chosen. Melodies are simple and stepwise (tone-deaf first: the Booth's follow-me mode moves them to
wherever you start). Writes script.json and script.csv.
"""
import csv, json, random, re, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from engine.song import phonemes
from engine.ds import VOWELS

TOK = {p: 1 for p in 'aa ae ah ao aw ax ay b ch d dh eh er ey f g hh ih iy jh k l m n ng ow oy p r s sh t th uh uw v w y z zh'.split()}
RANGE_LOW, RANGE_HIGH, HOME = 36, 52, 43          # C2..E3 around G2; the Booth's range check replaces these
MAJOR = [0, 2, 4, 5, 7, 9, 11]
rng = random.Random(7)


def phon_line(text):
    out = []
    for w in re.findall(r"[A-Za-z']+", text):
        out += phonemes(w, TOK) + ['|']
    return out[:-1]


def diphones(ph):
    seq = [p for p in ph if p != '|']
    return list(zip(seq, seq[1:]))


def melody(n_syl, key=HOME, bpm=90):
    """A stepwise line on the major scale around `key`: quarters, a few eighth pairs, a held last note."""
    degrees, d = [], 0
    for i in range(n_syl):
        d = max(-4, min(5, d + rng.choice([-1, -1, 0, 1, 1, 2, -2])))
        degrees.append(d)
    notes, t = [], 0.0
    for i, d in enumerate(degrees):
        last = i == n_syl - 1
        length = 2.0 if last else rng.choice([1.0, 1.0, 1.0, 0.5]) if i < n_syl - 2 else 1.0
        midi = key + 12 * (d // 7) + MAJOR[d % 7]
        notes.append({'beat': t, 'beats': length, 'midi': max(RANGE_LOW, min(RANGE_HIGH, midi))})
        t += length
    return {'bpm': bpm, 'notes': notes}


def balanced_lines(target=300, need=3):
    lines = []
    for raw in (HERE / 'cmuarctic.data').read_text().splitlines():
        m = re.search(r'"(.+)"', raw)
        if not m: continue
        for chunk in re.split(r'[,;:]', m.group(1)):
            text = chunk.strip(' .?!"\'')
            if not re.search('[A-Za-z]', text) or re.search(r'\d', text): continue
            ph = phon_line(text)
            syl = sum(p in VOWELS for p in ph)
            if 5 <= syl <= 11: lines.append((text, ph, syl))
    seen, chosen, have = set(), [], Counter()
    lines = [l for l in lines if not (l[0].lower() in seen or seen.add(l[0].lower()))]
    while len(chosen) < target:
        best, gain = None, 0
        for l in lines:
            g = sum(1 for dp in set(diphones(l[1])) if have[dp] < need)
            if g > gain: best, gain = l, g
        if best is None: break
        chosen.append(best); lines.remove(best)
        for dp in diphones(best[1]): have[dp] += 1
    return chosen, have


def main():
    rows = []
    vowels = [('ah', 'ah'), ('ee', 'iy'), ('oo', 'uw'), ('eh', 'eh'), ('oh', 'ow'), ('a (cat)', 'ae'), ('uh', 'ah'), ('eye', 'ay')]
    for name, ph in vowels:
        for m in range(RANGE_LOW, RANGE_HIGH + 1):
            rows.append({'set': 'A', 'text': f'{name} (hold)', 'syllables': 1, 'melody': {'bpm': 60, 'notes': [{'beat': 0, 'beats': 3, 'midi': m}]}})
    for syl in ['la', 'na', 'ma', 'da']:
        for bpm in (70, 110):
            for direction in ('up', 'down'):
                steps = MAJOR + [12] if direction == 'up' else list(reversed(MAJOR + [12]))
                rows.append({'set': 'B', 'text': f'{syl} ' * 8, 'syllables': 8, 'melody': {'bpm': bpm, 'notes': [{'beat': i, 'beats': 1, 'midi': RANGE_LOW + 4 + s} for i, s in enumerate(steps)]}})
    chosen, have = balanced_lines()
    for text, ph, syl in chosen:
        rows.append({'set': 'C', 'text': text, 'syllables': syl, 'phonemes': ' '.join(ph), 'melody': melody(syl)})
    for text, ph, syl in chosen[:20]:
        for style in ('soft', 'chest', 'belted', 'whispered'):
            rows.append({'set': 'E', 'text': text, 'style': style, 'syllables': syl, 'melody': melody(syl)})
    for i in range(20):
        rows.append({'set': 'F', 'text': rng.choice(['ah', 'oh', 'oo', 'ee']) + (' (with vibrato)' if i % 2 else ' (straight)'), 'syllables': 1,
                     'melody': {'bpm': 60, 'notes': [{'beat': 0, 'beats': 5, 'midi': rng.randint(RANGE_LOW + 2, RANGE_HIGH - 2)}]}})
    for g in ['in-breath'] * 10 + ['ooh'] * 7 + ['ah'] * 7 + ['hum'] * 6:
        rows.append({'set': 'G', 'text': g, 'syllables': 1, 'melody': {'bpm': 80, 'notes': [{'beat': 0, 'beats': 2, 'midi': HOME}]}})
    for i, r in enumerate(rows): r['id'] = f'{r["set"]}{i + 1:04d}'
    (HERE / 'script.json').write_text(json.dumps(rows, indent=1))
    with open(HERE / 'script.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['id', 'set', 'text', 'style', 'syllables', 'notes'])
        for r in rows: w.writerow([r['id'], r['set'], r['text'].strip(), r.get('style', ''), r['syllables'], ' '.join(str(n['midi']) for n in r['melody']['notes'])])
    all_dp = {(a, b) for a in TOK for b in TOK}
    covered = sum(1 for v in have.values() if v >= 3)
    print(f'{len(rows)} lines: ' + ', '.join(f'{s} {sum(r["set"] == s for r in rows)}' for s in 'ABCEFG')
          + f'; set C covers {len(have)} sound pairs ({covered} at least 3 times); D = your songs, added from Mortiflix Music')


if __name__ == '__main__':
    main()
