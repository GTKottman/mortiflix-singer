"""Latin words -> ARPAbet phonemes, by rule (church Latin, the way choirs sing it): every vowel is its own syllable
except the digraphs ae / oe (one "eh") and au (one "aw"); c and g soften before e / i / y / ae / oe; qu = "k w";
gn = "n y"; h is silent; j = "y"; x = "k s"; ti before a vowel = "t s iy" (not after s, t, x); doubled consonants sing once.

  phonemes('excelsis') -> ['eh', 'k', 'sh', 'eh', 'l', 's', 'iy', 's']
"""
import re

VOWEL = {'a': ['aa'], 'e': ['eh'], 'i': ['iy'], 'o': ['ao'], 'u': ['uw'], 'y': ['iy']}
SOFT = ('e', 'i', 'y', 'ae', 'oe')


def phonemes(word: str) -> list[str]:
    w = re.sub(r"[^a-zæœ]", '', word.lower().replace('æ', 'ae').replace('œ', 'oe').replace('v', 'v'))
    out, i = [], 0
    soft = lambda k: w.startswith(SOFT, k)
    while i < len(w):
        c, nxt = w[i], w[i + 1] if i + 1 < len(w) else ''
        if w.startswith(('ae', 'oe'), i): out.append('eh'); i += 2; continue
        if w.startswith('au', i): out.append('aw'); i += 2; continue
        if c in VOWEL: out += VOWEL[c]; i += 1; continue
        if w.startswith('qu', i): out += ['k', 'w']; i += 2; continue
        if w.startswith('gn', i): out += ['n', 'y']; i += 2; continue
        if w.startswith('ch', i): out.append('k'); i += 2; continue
        if w.startswith('ph', i): out.append('f'); i += 2; continue
        if w.startswith('th', i): out.append('t'); i += 2; continue
        if w.startswith('sc', i) and soft(i + 2): out.append('sh'); i += 2; continue
        if w.startswith('xc', i) and soft(i + 2): out += ['k', 'sh']; i += 2; continue
        if c == 't' and nxt == 'i' and i + 2 < len(w) and w[i + 2] in VOWEL and (i == 0 or w[i - 1] not in 'stx'):
            out += ['t', 's']; i += 1; continue
        if c == nxt and c not in VOWEL: i += 1; continue   # doubled consonant: sung once (the second one decides c/g)
        if c == 'c': out.append('ch' if soft(i + 1) else 'k'); i += 1; continue
        if c == 'g': out.append('jh' if soft(i + 1) else 'g'); i += 1; continue
        if c == 'h': i += 1; continue
        if c == 'j': out.append('y'); i += 1; continue
        if c == 'x': out += ['k', 's']; i += 1; continue
        if c == 'z': out += ['d', 'z']; i += 1; continue
        if c in 'bdfklmnprstvw': out.append({'w': 'v'}.get(c, c)); i += 1; continue
        i += 1
    return out


def syllables(word: str) -> int:
    return sum(p in ('aa', 'eh', 'iy', 'ao', 'uw', 'aw') for p in phonemes(word))
