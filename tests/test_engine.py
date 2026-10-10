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


def _sung(sr, notes, detune_cents, vib_cents=0):
    """A voice-like tone: harmonics with a vocal-ish envelope, each note detuned, optional 5.5 Hz vibrato."""
    out = []
    for s, d, m in notes:
        t = np.arange(int(d / 1000 * sr)) / sr
        f = 440 * 2 ** ((m + detune_cents / 100 - 69) / 12) * 2 ** (vib_cents / 1200 * np.sin(2 * np.pi * 5.5 * t))
        ph = 2 * np.pi * np.cumsum(f) / sr
        y = sum(np.sin(k * ph) / k * np.exp(-((k * f.mean() - 700) / 900) ** 2) for k in range(1, 30))
        out.append(y * np.hanning(len(t)) ** 0.2)
    return np.concatenate(out).astype(np.float32) * 0.2


def test_corrector_centres_notes_and_keeps_vibrato():
    from engine.correct import correct
    sr = 44100
    notes = [(0.0, 600.0, 57), (600.0, 600.0, 60), (1200.0, 600.0, 62)]
    y = _sung(sr, notes, detune_cents=45, vib_cents=30)
    out, rep = correct(y, sr, notes=notes, amount=1.0, speed=60, vibrato=True)
    for r in rep['notes']:
        assert abs(r['cents_before'] - 45) < 15 and abs(r['cents_after']) < 12
    half, _ = correct(y, sr, notes=notes, amount=0.5)
    assert len(out) == len(y) and np.isfinite(out).all()


def test_corrector_key_mode_snaps_to_the_scale():
    from engine.correct import correct
    sr = 44100
    y = _sung(sr, [(0.0, 700.0, 61)], detune_cents=0)            # C#4, not in C major
    _, rep = correct(y, sr, key=(0, 'major'), amount=1.0, speed=0, vibrato=False)
    after = [m for _, m in rep['after'] if m is not None]
    assert abs(np.median(after) - 60) < 0.15 or abs(np.median(after) - 62) < 0.15  # moved onto C or D


def test_latin_words():
    from engine.lang_la import phonemes, syllables
    assert phonemes('excelsis') == ['eh', 'k', 'sh', 'eh', 'l', 's', 'iy', 's']
    assert phonemes('Agnus') == ['aa', 'n', 'y', 'uw', 's'] and phonemes('qui') == ['k', 'w', 'iy']
    assert phonemes('peccata') == ['p', 'eh', 'k', 'aa', 't', 'aa'] and phonemes('caelum')[0] == 'ch'
    assert syllables('Kyrie') == 3 and syllables('aeterna') == 3
    assert song.words_of([[0.0, 400.0, 60]], ['Deo'], TOKENS, 'la')[0].phonemes == ['d', 'eh', 'ao']


@pytest.mark.skipif(not VOICE.exists(), reason='no voice installed')
def test_tone_retake_keeps_the_pitch(tmp_path):
    from engine.project import render_track
    v = Voice(VOICE, ROOT / 'voices/nsf_hifigan')
    p = {'ppq': 480, 'tempo': [{'tick': 0, 'bpm': 120}], 'tracks': []}
    t = {'id': 't1', 'notes': [{'id': f'n{i}', 'tick': i * 480, 'dur': 480, 'pitch': m, 'lyric': w} for i, (m, w) in enumerate([(60, 'la'), (64, 'la'), (62, 'la')])],
         'params': {'steps': 4}}
    a = render_track(v, 'SPORE', p, t, tmp_path)[0]
    t['tone_takes'] = {str(a['first_tick']): 1}
    b = render_track(v, 'SPORE', p, t, tmp_path)[0]
    pa, pb = np.array(a['pitch'])[:, 1], np.array(b['pitch'])[:, 1]
    n = min(len(pa), len(pb))
    assert b['hash'] != a['hash'] and np.abs(pa[:n] - pb[:n]).max() < 0.05      # new tone, the same pitch curve


def test_spanish_and_italian_words():
    from engine.lang_rules import spanish, italian
    assert spanish('corazón') == ['k', 'ow', 'r', 'aa', 's', 'ow', 'n'] and spanish('quiero') == ['k', 'y', 'eh', 'r', 'ow']
    assert spanish('niño') == ['n', 'iy', 'n', 'y', 'ow'] and spanish('rey') == ['r', 'eh', 'y']
    assert italian('figlio') == ['f', 'iy', 'l', 'y', 'ow'] and italian('scena') == ['sh', 'eh', 'n', 'aa']
    assert italian('acqua') == ['aa', 'k', 'w', 'aa'] and italian('ciao') == ['ch', 'aa', 'ow']      # sung "cia-o"
    assert spanish('y') == ['iy'] and spanish('hoy') == ['ow', 'y']


def test_japanese_kana_and_romaji():
    from engine.lang_rules import japanese
    assert japanese('さくら') == japanese('sakura') == ['s', 'aa', 'k', 'uw', 'r', 'aa']
    assert japanese('きゃく') == ['k', 'y', 'aa', 'k', 'uw'] and japanese('しゃしん') == ['sh', 'aa', 'sh', 'iy', 'n']
    assert japanese('がっこう') == ['g', 'aa', 'k', 'ow', 'uw'] and japanese('tsuki') == ['t', 's', 'uw', 'k', 'iy']
