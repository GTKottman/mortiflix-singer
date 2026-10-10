"""Fast engine tests (no models needed), plus one real render when a voice is installed."""
import os, sys
from pathlib import Path
import numpy as np, pytest
sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.ds import frames_from_ms, fit_sum, Voice, Word, Note
from engine import song

ROOT = Path(__file__).parent.parent
TOKENS = {p: i for i, p in enumerate('SP AP aa ae ah ao aw ax ay b ch d dh eh er ey f g hh ih iy jh k l m n ng ow oy p r s sh t th uh uw v w y z zh'.split())}


def test_frames_never_drift():
    fm = 512 / 44100 * 1000
    durs = [37.3] * 500
    f = frames_from_ms(durs, fm)
    assert abs(sum(f) * fm - sum(durs)) < fm          # the total stays within one frame however many pieces


def test_fit_sum_takes_from_the_end():
    assert fit_sum([5, 5, 5], 12) == [5, 5, 2]
    assert sum(fit_sum([5, 5, 1], 7)) == 7


def test_words_split_holds_and_silences():
    notes = [[i * 500.0, 450.0, 60 + i] for i in range(6)]
    words = song.words_of(notes, ['keep', 'sun-', 'rise', '_', '.', 'now'], TOKENS)
    assert [len(w.notes) for w in words] == [1, 3, 1]        # sunrise covers its two notes + the hold
    assert words[1].holds == {2}
    assert words[1].phonemes == ['s', 'ah', 'n', 'r', 'ay', 'z']
    assert words[2].notes[0].start == 2500.0                  # the silent note is gone


def test_hand_spelled_phonemes():
    assert song.phonemes('live{l ay v}', TOKENS) == ['l', 'ay', 'v']


def test_phrases_break_at_rests():
    notes = [[0, 400, 60], [500, 400, 60], [2000, 400, 60]]
    words = song.words_of(notes, ['a', 'b', 'c'], TOKENS)
    assert [len(p) for p in song.phrases_of(words)] == [2, 1]


VOICE = ROOT / 'voices/SPORE/SPORE'


@pytest.mark.skipif(not VOICE.exists(), reason='no voice installed')
def test_real_render_anchors_vowels_and_tunes_notes():
    v = Voice(VOICE, ROOT / 'voices/nsf_hifigan')
    notes = [[1000.0, 450.0, 62], [1500.0, 450.0, 64], [2000.0, 900.0, 66]]
    words = song.words_of(notes, ['ride', 'the', 'light'], v.tokens)
    phones, end = v.layout(words)
    vowels = [s for p, s, e in phones if p in ('ay', 'ah', 'ax')]
    assert np.allclose(vowels, [1000.0, 1500.0, 2000.0], atol=v.frame_ms)   # each vowel starts on its note
    assert phones[0][0] == 'r' and phones[0][1] < 1000.0                     # "r" leads in before the beat
    wav, t0, c = v.render_phrase(words, steps=4, pitch_steps=4)
    p, fm = c['pitch'], c['frame_ms']
    for s, d, m in notes:                                                     # the correction layer centres every note
        a, b = int((s - t0) / fm), int((s + d - t0) / fm)
        mid = p[a + (b - a) // 5: a + 4 * (b - a) // 5]
        assert abs(np.median(mid) - m) < 0.1
    assert np.abs(wav).max() > 0.01
