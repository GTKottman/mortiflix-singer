"""Song level: MIDI + lyrics -> phrases of words -> one WAV on the song timeline (bar 1 = 0 s).

Lyrics: one token per note, in order. "sun-" + "rise" = one word over two notes; "_" holds the last vowel onto a new
note; "." leaves a note silent; "word{ph1 ph2 ...}" spells a word's phonemes by hand.
"""
from __future__ import annotations
import re
from pathlib import Path
import numpy as np
import mido
from .ds import Voice, Note, Word, VOWELS

_g2p = None


def phonemes(word: str, voice_tokens) -> list[str]:
    m = re.search(r'\{(.+?)\}', word)
    if m: return m.group(1).split()
    global _g2p
    if _g2p is None:
        from g2p_en import G2p
        _g2p = G2p()
    w = re.sub(r"[^A-Za-z']", '', word).lower()
    out = [re.sub(r'\d', '', p).lower() for p in _g2p(w) if re.match(r"^[A-Za-z]+\d?$", p)]
    return [p for p in out if p in voice_tokens]


def read_midi(path, channel=None):
    """Notes (start ms, dur ms, pitch) of one part, through the file's tempo map; overlaps cut (one voice)."""
    mf = mido.MidiFile(path)
    ev = []
    for tr in mf.tracks:
        t = 0
        for m in tr: t += m.time; ev.append((t, m))
    ev.sort(key=lambda e: e[0])
    tempo, last, sec, on, notes = 500000, 0, 0.0, {}, []
    for t, m in ev:
        sec += mido.tick2second(t - last, mf.ticks_per_beat, tempo); last = t
        if m.type == 'set_tempo': tempo = m.tempo
        elif m.type in ('note_on', 'note_off') and (channel is None or m.channel == channel):
            if m.type == 'note_on' and m.velocity > 0: on[m.note] = sec
            elif m.note in on: s = on.pop(m.note); notes.append([s * 1000, (sec - s) * 1000, m.note])
    notes.sort()
    for a, b in zip(notes, notes[1:]):
        if a[0] + a[1] > b[0]: a[1] = b[0] - a[0]
    return notes


def words_of(notes, tokens, voice_tokens):
    """Pair notes with lyric tokens into Words (silent notes dropped)."""
    words, cur = [], None
    for (s, d, p), tok in zip(notes, tokens):
        n = Note(s, d, float(p), tok)
        if tok == '.': cur = None; continue
        if tok == '_' and words:
            words[-1].holds.add(len(words[-1].notes)); words[-1].notes.append(n); continue
        if cur is not None:
            cur.notes.append(n); cur.text += tok.rstrip('-')
        else:
            cur = Word([n], []); cur.text = tok.rstrip('-'); words.append(cur)
        if not tok.endswith('-'):
            cur.phonemes = phonemes(cur.text, voice_tokens) or ['ah']; cur = None
    if cur is not None: cur.phonemes = phonemes(cur.text, voice_tokens) or ['ah']
    return words


def phrases_of(words, gap_ms=300.0, max_ms=12000.0):
    out = [[words[0]]]
    for a, b in zip(words, words[1:]):
        end = a.notes[-1].start + a.notes[-1].dur
        if b.notes[0].start - end >= gap_ms or b.notes[-1].start - out[-1][0].notes[0].start > max_ms: out.append([b])
        else: out[-1].append(b)
    return out


def render(voice: Voice, notes, tokens, transpose=0, **kw):
    notes = [[s, d, p + transpose] for s, d, p in notes]
    words = words_of(notes, tokens, voice.tokens)
    phr = phrases_of(words)
    end_ms = max(n.start + n.dur for w in words for n in w.notes) + 1500
    out = np.zeros(int(end_ms / 1000 * voice.sr), np.float32)
    for i, ph in enumerate(phr):
        wav, t0, _ = voice.render_phrase(ph, seed=i, **kw)
        a = int(round(t0 / 1000 * voice.sr))
        if a < 0: wav, a = wav[-a:], 0
        n = min(len(wav), len(out) - a)
        fade = np.ones(n, np.float32); k = min(441, n // 2)
        fade[:k] = np.linspace(0, 1, k); fade[n - k:] = np.linspace(1, 0, k)
        out[a:a + n] += wav[:n] * fade
    return out, phr
