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


@pytest.mark.skipif(not VOICE.exists(), reason='no voice installed')
def test_consonant_lead_in_is_editable():
    v = Voice(VOICE, ROOT / 'voices/nsf_hifigan')
    notes = [[1000.0, 450.0, 62], [1500.0, 450.0, 64]]
    words = song.words_of(notes, ['the', 'street'], v.tokens)
    phones, _ = v.layout(words)
    natural = 1500.0 - next(s for p, s, e in phones if p == 's')
    words[1].notes[0].lead = 250.0
    phones, _ = v.layout(words)
    s_start = next(s for p, s, e in phones if p == 's')
    assert abs((1500.0 - s_start) - 250.0) < 1.0 and abs(natural - 250.0) > 5     # "s t r" now start 250 ms early
    assert all(e > s for p, s, e in phones) and all(abs(a[2] - b[1]) < 1e-6 for a, b in zip(phones, phones[1:]))


def test_breath_tokens_become_breaths():
    words = song.words_of([[0.0, 400.0, 60], [500.0, 400.0, 62]], ['br', 'go'], TOKENS)
    assert words[0].phonemes == ['AP'] and words[1].phonemes == ['g', 'ow']


@pytest.mark.skipif(not VOICE.exists(), reason='no voice installed')
def test_phoneme_lengths_scale_and_still_fit_the_notes():
    v = Voice(VOICE, ROOT / 'voices/nsf_hifigan')
    notes = [[0.0, 700.0, 62], [700.0, 700.0, 64]]
    length = lambda phones, i: phones[i][2] - phones[i][1]
    words = song.words_of(notes, ['street', 'light'], v.tokens)
    before, _ = v.layout(words)
    words[0].scales = [1, 1, 1, 1, 3]                                      # the final "t" of street, x3
    after, _ = v.layout(words)
    assert length(after, 4) > 1.8 * length(before, 4)
    vowels = [s for p, s, e in after if p in ('iy', 'ay')]
    assert np.allclose(vowels, [0.0, 700.0], atol=v.frame_ms)               # vowels still start on their notes


@pytest.mark.skipif(not VOICE.exists(), reason='no voice installed')
def test_glide_sets_the_slide_length():
    v = Voice(VOICE, ROOT / 'voices/nsf_hifigan')
    notes = [[0.0, 600.0, 62], [600.0, 600.0, 67], [1200.0, 600.0, 62]]

    def slope(glide):
        words = song.words_of(notes, ['la', 'la', 'la'], v.tokens)
        words[1].notes[0].glide = glide
        _, t0, c = v.render_phrase(words, steps=4, pitch_steps=4)
        p, fm = c['pitch'], c['frame_ms']
        k = lambda ms: int((ms - t0) / fm)
        return float(np.max(np.abs(np.diff(p[k(450):k(750)]))))          # steepest step per frame around the change
    assert slope(400) < 0.5 * slope(40)


def test_note_groups_expand_to_notes():
    from engine.project import expand_groups
    p = {'tracks': [{'id': 't1', 'notes': [{'id': 'a', 'tick': 0, 'dur': 480, 'pitch': 60, 'lyric': 'go'}],
                     'refs': [{'id': 'r1', 'group': 'g1', 'tick': 1920, 'transpose': 2}, {'id': 'r2', 'group': 'g1', 'tick': 3840}]}],
         'groups': {'g1': {'name': 'hook', 'notes': [{'id': 'x', 'tick': 0, 'dur': 240, 'pitch': 62, 'lyric': 'la'},
                                                    {'id': 'y', 'tick': 240, 'dur': 240, 'pitch': 64, 'lyric': 'la'}]}}}
    e = expand_groups(p)
    ns = sorted(e['tracks'][0]['notes'], key=lambda n: n['tick'])
    assert [(n['id'], n['tick'], n['pitch']) for n in ns] == [('a', 0, 60), ('r1~x', 1920, 64), ('r1~y', 2160, 66), ('r2~x', 3840, 62), ('r2~y', 4080, 64)]
    assert 'groups' not in e and 'refs' not in e['tracks'][0] and p['tracks'][0]['refs']      # the original is untouched
