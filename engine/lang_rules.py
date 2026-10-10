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


# ---- Japanese: kana (hiragana or katakana) or romaji -> ARPAbet; every mora's vowel sings, "n" before a consonant or
# at the end is its own nasal, small tsu doubles the next consonant (sung once, so dropped) ----
_KANA = {}
_rows = ('a i u e o', 'ka ki ku ke ko', 'sa shi su se so', 'ta chi tsu te to', 'na ni nu ne no', 'ha hi fu he ho',
         'ma mi mu me mo', 'ya - yu - yo', 'ra ri ru re ro', 'wa - - - wo', 'ga gi gu ge go', 'za ji zu ze zo',
         'da ji zu de do', 'ba bi bu be bo', 'pa pi pu pe po')
_hira = ('あいうえお', 'かきくけこ', 'さしすせそ', 'たちつてと', 'なにぬねの', 'はひふへほ', 'まみむめも', 'や-ゆ-よ', 'らりるれろ',
         'わ---を', 'がぎぐげご', 'ざじずぜぞ', 'だぢづでど', 'ばびぶべぼ', 'ぱぴぷぺぽ')
for _r, _h in zip(_rows, _hira):
    for _ro, _k in zip(_r.split(), _h):
        if _k != '-' and _ro != '-':
            _KANA[_k] = _ro; _KANA[chr(ord(_k) + 0x60)] = _ro      # katakana sits 0x60 above hiragana
_KANA.update({'ん': 'n', 'ン': 'n', 'ー': '-'})
_SMALL = {'ゃ': 'ya', 'ゅ': 'yu', 'ょ': 'yo', 'ャ': 'ya', 'ュ': 'yu', 'ョ': 'yo'}
_JV = {'a': 'aa', 'i': 'iy', 'u': 'uw', 'e': 'eh', 'o': 'ow'}
_JC = {'k': ['k'], 'g': ['g'], 's': ['s'], 'sh': ['sh'], 'z': ['z'], 'j': ['jh'], 't': ['t'], 'ch': ['ch'], 'ts': ['t', 's'],
       'd': ['d'], 'n': ['n'], 'h': ['hh'], 'f': ['f'], 'b': ['b'], 'p': ['p'], 'm': ['m'], 'y': ['y'], 'r': ['r'], 'w': ['w'],
       'ky': ['k', 'y'], 'gy': ['g', 'y'], 'ny': ['n', 'y'], 'hy': ['hh', 'y'], 'by': ['b', 'y'], 'py': ['p', 'y'],
       'my': ['m', 'y'], 'ry': ['r', 'y']}


def kana_to_romaji(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c in ('っ', 'ッ'): out.append('Q'); i += 1; continue           # small tsu: a held stop, sung as a gap
        r = _KANA.get(c)
        if r is None: out.append(c); i += 1; continue
        if i + 1 < len(text) and text[i + 1] in _SMALL:                  # きゃ -> kya, しゃ -> sha, ちゃ -> cha
            sm = _SMALL[text[i + 1]]; base = r[:-1]
            r = (base if base in ('sh', 'ch', 'j') else base + 'y') + sm[1] if base not in ('sh', 'ch', 'j') else base + sm[1]
            i += 1
        if r == '-' and out: r = out[-1][-1]                               # ー lengthens the vowel before it
        out.append(r); i += 1
    return ''.join(out)


def japanese(word: str) -> list[str]:
    w = kana_to_romaji(word).lower()
    w = re.sub(r'[^a-zq]', '', w)
    out, i = [], 0
    while i < len(w):
        if w[i] in _JV: out.append(_JV[w[i]]); i += 1; continue
        if w[i] == 'q': i += 1; continue                                    # small tsu: the doubled stop sings once
        if w[i] == 'n' and (i + 1 == len(w) or (w[i + 1] not in _JV and w[i + 1] != 'y')): out.append('n'); i += 1; continue
        for L in (2, 1):
            c = w[i:i + L]
            if c in _JC and i + L < len(w) and (w[i + L] in _JV):
                out += _JC[c]; i += L; break
        else:
            if w[i] == w[i + 1:i + 2]: i += 1; continue                       # romaji double consonant (kitte)
            if w[i] in _JC: out += _JC[w[i]]
            i += 1
    return out
