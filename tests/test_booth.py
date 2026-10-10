"""Booth grading, tone-deaf first: steady-but-off-key passes, wobbling, clipping, quiet and noisy takes don't."""
import json, sys, warnings
from pathlib import Path
import numpy as np, pytest, soundfile as sf
warnings.filterwarnings('ignore')
sys.path.insert(0, str(Path(__file__).parent.parent))
from booth.grade import grade

TAKE = Path.home() / 'Documents/programs/robovox/songs/voice-clips/better_off_2.wav'
LINE = {'set': 'A', 'text': 'ah', 'melody': {'bpm': 90, 'notes': [{'beat': 0, 'beats': 3, 'midi': 43}]}}


def voice(semitone_curve):
    """A real voice (the owner's take) re-sung by WORLD on the given pitch curve (semitones per 5 ms frame)."""
    import pyworld as pw
    y, sr = sf.read(TAKE); y = y[:sr * 3].astype(np.float64)
    f0, t = pw.harvest(y, sr, frame_period=5.0, f0_floor=55, f0_ceil=600)
    sp, ap = pw.cheaptrick(y, f0, t, sr), pw.d4c(y, f0, t, sr)
    curve = np.resize(semitone_curve, len(f0))
    f1 = np.where(f0 > 0, 440 * 2 ** ((curve - 69) / 12), 0)
    out = pw.synthesize(f1, sp, ap, sr, 5.0)
    return np.concatenate([np.random.default_rng(0).normal(0, 1e-4, sr // 2), out]), sr


@pytest.mark.skipif(not TAKE.exists(), reason='no recording on this machine')
def test_steady_but_off_key_passes():
    y, sr = voice(np.full(600, 40.0))                       # a minor third under the guide, rock steady
    g = grade(y, sr, LINE, preroll_s=0.5)
    assert g['grade'] in ('A', 'B'), g
    assert g['key_offset'] == -3


@pytest.mark.skipif(not TAKE.exists(), reason='no recording on this machine')
def test_wobble_is_flagged():
    t = np.arange(600) * 0.005
    y, sr = voice(43 + 1.5 * np.sin(2 * np.pi * 1.3 * t))
    assert grade(y, sr, LINE, preroll_s=0.5)['grade'] == 'C'


def test_clipped_and_quiet():
    sr = 16000
    loud = np.clip(5 * np.sin(np.arange(sr) * 0.05), -1, 1)
    assert any('clipped' in p for p in grade(loud, sr, LINE)['problems'])
    assert any('too quiet' in p or 'no singing' in p for p in grade(loud * 0.001, sr, LINE)['problems'])


def test_noisy_room_from_preroll():
    sr = 16000
    y = np.concatenate([np.random.default_rng(1).normal(0, 0.05, sr // 2), np.zeros(sr)])
    assert any('noisy' in p for p in grade(y, sr, LINE, preroll_s=0.5)['problems'])
