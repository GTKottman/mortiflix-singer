"""Trainer pieces that need no models: dataset rows from an alignment, the dictionary, the test-set labels."""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / 'trainer'))
import build_dataset, make_synthetic, train


class FakeAligner:
    def align(self, y, sr, phones):
        t = 0.3; step = (len(y) / sr - 0.6) / len(phones); out = []
        for p in phones: out.append((p, t, t + step)); t += step
        return out


def check_row(r):
    seq, dur, num = r['ph_seq'].split(), [float(x) for x in r['ph_dur'].split()], [int(x) for x in r['ph_num'].split()]
    ns, nd = r['note_seq'].split(), [float(x) for x in r['note_dur'].split()]
    assert len(seq) == len(dur) == sum(num) and len(ns) == len(nd) == len(num)
    assert abs(sum(dur) - sum(nd)) < 1e-3 and min(dur) > 0
    return seq, ns


def test_rows_label_what_was_sung():
    sr = 44100; t = np.arange(int(sr * 2.0)) / sr
    y = sum(np.sin(2 * np.pi * 220 * k * t) / k for k in range(1, 12)).astype(np.float32) * 0.2    # A3, harmonic-rich
    phones = build_dataset.line_phonemes('ah (hold)')
    y2, row = build_dataset.rows_for('x', y, sr, phones, FakeAligner())
    seq, notes = check_row(row)
    assert seq == ['SP', 'aa', 'SP'] and [n for n in notes if n != 'rest'] == ['A3']


def test_line_phonemes():
    assert build_dataset.line_phonemes('in-breath') is None
    assert build_dataset.line_phonemes('ee (hold)') == ['iy']
    assert build_dataset.line_phonemes('the cat') == ['dh', 'ah', 'k', 'ae', 't']


def test_dictionary_only_has_recorded_phonemes(tmp_path):
    (tmp_path / 'transcriptions.csv').write_text('name,ph_seq,ph_dur\na,SP AP k ae t SP,0.1 0.1 0.1 0.1 0.1 0.1\n')
    missing, breaths = train.write_dictionary(tmp_path / 'd.txt', tmp_path)
    assert breaths and 'iy' in missing
    assert (tmp_path / 'd.txt').read_text().split('\n')[:3] == ['ae\tae', 'k\tk', 't\tt']


def test_synthetic_labels_consistent():
    W, N = make_synthetic.Word, make_synthetic.Note
    words = [W([N(500, 400, 60, 'br')], ['AP']), W([N(1000, 500, 60, '')], ['k', 'ae', 't']), W([N(1500, 500, 62, '')], ['s', 'ay'])]
    phones = [('AP', 500, 900), ('k', 900, 1000), ('ae', 1000, 1400), ('t', 1400, 1450), ('s', 1450, 1500), ('ay', 1500, 2000)]
    seq, dur, num, ns, nd = make_synthetic.labels(phones, 0, 2.5, words)
    check_row({'ph_seq': ' '.join(seq), 'ph_dur': ' '.join(map(str, dur)), 'ph_num': ' '.join(map(str, num)),
               'note_seq': ' '.join(ns), 'note_dur': ' '.join(map(str, nd))})
    assert [n for n in ns if n != 'rest'] == ['C4', 'D4']


def breathy(sr, total=2.0, at=(0.5, 1.1), level_db=-35, seed=0):
    """A quiet room with a breath-like burst: band-limited noise with a rise and fall."""
    from scipy.signal import butter, sosfilt
    rng = np.random.default_rng(seed)
    y = rng.normal(0, 10 ** (-72 / 20), int(sr * total))
    a, b = int(at[0] * sr), int(at[1] * sr)
    burst = sosfilt(butter(4, [500, 4000], 'bandpass', fs=sr, output='sos'), rng.normal(0, 1, b - a))
    burst *= np.hanning(b - a) / np.sqrt(np.mean(burst ** 2)) * 10 ** (level_db / 20) * 1.6
    y[a:b] += burst
    return y.astype(np.float32)


def test_breath_found():
    sr = 44100
    br = build_dataset.find_breath(breathy(sr), sr, 0, 2.0)
    assert br and abs(br[0] - 0.5) < 0.2 and abs(br[1] - 1.1) < 0.2
    assert build_dataset.find_breath(breathy(sr, level_db=-90), sr, 0, 2.0) is None


def test_in_breath_line_row():
    sr = 44100
    _, row = build_dataset.rows_for('b', breathy(sr), sr, [], FakeAligner())
    seq, notes = check_row(row)
    assert seq == ['SP', 'AP', 'SP'] and notes == ['rest']


def test_training_kit_installs_with_fake_downloads(tmp_path, monkeypatch):
    """The whole kit install against fake downloads: sources copied, uv unpacked, DiffSinger and BigVGAN unpacked at
    their pinned names, the venv and packages requested through uv, and a rerun skips what is done."""
    import io, tarfile, zipfile, subprocess
    import kit
    root = Path(__file__).parent.parent

    def tgz(name, data):
        b = io.BytesIO()
        with tarfile.open(fileobj=b, mode='w:gz') as t:
            info = tarfile.TarInfo(f'uv-x/{name}'); info.size = len(data); t.addfile(info, io.BytesIO(data))
        return b.getvalue()

    def zipped(top, files):
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            for n, d in files.items(): z.writestr(f'{top}/{n}', d)
        return b.getvalue()

    got = []
    def fake_get(url, progress, label):
        got.append(url)
        if 'astral-sh/uv' in url: return tgz('uv', b'#!/bin/sh\n')
        if 'DiffSinger' in url: return zipped(f'DiffSinger-{kit.DS_REV}', {'scripts/train.py': '', 'requirements.txt': 'click\n'})
        return zipped(f'BigVGAN-{kit.BV_REV}', {'train.py': ''})
    calls = []
    def fake_run(cmd, check=False, cwd=None, **kw):
        calls.append([str(c) for c in cmd])
        if 'venv' in cmd:                     # uv venv: make the interpreter appear
            py = kit.python_of(tmp_path); py.parent.mkdir(parents=True, exist_ok=True); py.write_text('')
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(kit, '_get', fake_get); monkeypatch.setattr(kit.subprocess, 'run', fake_run)

    k = kit.install(tmp_path, root, progress=lambda m: None)
    assert (k / 'trainer' / 'train.py').exists() and (k / 'engine' / 'ds.py').exists() and (k / 'booth' / 'script.json').exists()
    assert (k / 'ref' / 'DiffSinger' / 'scripts' / 'train.py').exists() and (k / 'ref' / 'BigVGAN' / 'train.py').exists()
    assert kit.ready(tmp_path) and any('venv' in c for c in calls) and any('torch' in c for c in calls)
    n = len(got); kit.install(tmp_path, root, progress=lambda m: None)
    assert len(got) == n                       # nothing downloaded again
