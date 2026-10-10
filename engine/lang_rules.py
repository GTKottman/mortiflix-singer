"""Spanish and Italian words -> ARPAbet phonemes, by spelling rules (both languages spell the way they sound).
Every vowel sings as its own syllable except the i/u glides next to another vowel; doubled consonants sing once.
The voices are English, so the nearest English sounds stand in (Spanish/Italian "o" -> ow, rolled r -> r)."""
import re

V = {'a': 'aa', 'e': 'eh', 'i': 'iy', 'o': 'ow', 'u': 'uw'}
ACC = str.maketrans('áéíóúàèìòùü', 'aeiouaeiouu')


def _vowel(w, i, out):
    """i/u between or before another vowel glide (y/w) instead of singing their own syllable."""
    c = w[i]; prev = w[i - 1] if i else ''; nxt = w[i + 1] if i + 1 < len(w) else ''
    if c in 'iu' and nxt in V and nxt != c and prev not in ('q', 'g'):
        out.append('y' if c == 'i' else 'w'); return
    if c in 'iu' and prev in V and prev not in 'iu' and nxt not in V:      # falling diphthong: "rey", "hoy", "auto"
        out.append('y' if c == 'i' else 'w'); return
    out.append(V[c])


def syllables(phones) -> int:
    return max(1, sum(p in ('aa', 'eh', 'iy', 'ow', 'uw') for p in phones))


def spanish(word: str) -> list[str]:
    raw = word.lower()
    w = re.sub(r'[^a-zñ]', '', raw.translate(ACC))
    out, i = [], 0
    while i < len(w):
        c, nxt = w[i], w[i + 1] if i + 1 < len(w) else ''
        soft = nxt in ('e', 'i')
        if c in V: _vowel(w, i, out); i += 1; continue
        if w.startswith('ch', i): out.append('ch'); i += 2; continue
        if w.startswith('ll', i): out.append('y'); i += 2; continue
        if w.startswith('rr', i): out.append('r'); i += 2; continue
        if w.startswith('qu', i): out.append('k'); i += 2; continue
        if w.startswith('gu', i) and i + 2 < len(w) and w[i + 2] in 'ei': out.append('g'); i += 2; continue
        if c == 'ñ': out += ['n', 'y']; i += 1; continue
        if c == 'c': out.append('s' if soft else 'k'); i += 1; continue
        if c == 'g': out.append('hh' if soft else 'g'); i += 1; continue
        if c == 'j': out.append('hh'); i += 1; continue
        if c == 'z': out.append('s'); i += 1; continue
        if c == 'h': i += 1; continue
        if c == 'v': out.append('b'); i += 1; continue
        if c == 'x': out += ['k', 's']; i += 1; continue
        if c == 'y':                         # "y" alone or after a consonant sings "ee"; after a vowel it glides
            out.append('y' if nxt in V or (i and w[i - 1] in V) else 'iy'); i += 1; continue
        if c == nxt: i += 1; continue
        if c in 'bdfklmnprstw': out.append(c); i += 1; continue
        i += 1
    return out


def italian(word: str) -> list[str]:
    w = re.sub(r'[^a-z]', '', word.lower().translate(ACC))
    out, i = [], 0
    while i < len(w):
        c, nxt = w[i], w[i + 1] if i + 1 < len(w) else ''
        soft = nxt in ('e', 'i')
        if c in V:
            # the i in cia/gia/scia only softens the consonant before it
            if c == 'i' and i > 0 and w[i - 1] in 'cg' and nxt in V and nxt != 'i': i += 1; continue
            _vowel(w, i, out); i += 1; continue
        if w.startswith('gli', i): out += ['l', 'y']; i += 3 if i + 3 < len(w) and w[i + 3] in V else 2; continue
        if w.startswith('gn', i): out += ['n', 'y']; i += 2; continue
        if w.startswith('sc', i) and i + 2 < len(w) and w[i + 2] in 'ei': out.append('sh'); i += 2; continue
        if w.startswith('ch', i) or w.startswith('gh', i): out.append('k' if c == 'c' else 'g'); i += 2; continue
        if w.startswith('qu', i): out += ['k', 'w']; i += 2; continue
        if c == nxt or (c == 'c' and nxt == 'q'): i += 1; continue     # doubled (and "cq") sing once
        if c == 'c': out.append('ch' if soft else 'k'); i += 1; continue
        if c == 'g': out.append('jh' if soft else 'g'); i += 1; continue
        if c == 'z': out += ['t', 's']; i += 1; continue
        if c == 'h': i += 1; continue
        if c in 'bdfklmnprstvw': out.append(c); i += 1; continue
        i += 1
    return out
