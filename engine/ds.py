"""DiffSinger voice runner: notes + words -> sung audio, driving a voice package's ONNX models.

The method follows OpenUtau's DiffSinger renderer (MIT): a phrase's phonemes are grouped so every note's vowel is
anchored to the note's start, the duration model's lengths are stretched between those anchors, the pitch model draws
a natural curve from the notes, the variance model adds breath/tension/energy/voicing, the acoustic model draws the
mel spectrogram and the NSF-HiFiGAN vocoder turns it into audio. On top of OpenUtau's method, the predicted pitch is
centred on each written note (Mortiflix Singer's correction layer) so it is in tune by construction.
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import onnxruntime as ort
import yaml

HEAD, TAIL = 8, 8              # padding frames before and after a phrase (OpenUtau's values)
PAD_MS = 500.0                 # room before the first note for its leading consonants
VOWELS = {'aa', 'ae', 'ah', 'ao', 'aw', 'ax', 'ay', 'eh', 'er', 'ey', 'ih', 'iy', 'ow', 'oy', 'uh', 'uw'}
GLIDES = {'w', 'y'}


@dataclass
class Note:
    start: float               # ms
    dur: float                 # ms
    midi: float
    lyric: str                 # a word, "sun-" (syllable the next note finishes), "_" (hold), "." (silent)


@dataclass
class Word:
    notes: list[Note]          # the word's first note, then its syllable and hold notes
    phonemes: list[str]
    holds: set[int] = field(default_factory=set)   # indexes into notes that only hold the previous vowel


def frames_from_ms(durs_ms, frame_ms):
    """OpenUtau's DurationsMsToFrames: cumulative rounding, so the total never drifts."""
    out, acc, prev = [], 0.0, 0
    for d in durs_ms:
        acc += d
        f = int(round(acc / frame_ms + 0.5))          # Python rounds halves to even, like OpenUtau's MidpointRounding.ToEven
        out.append(f - prev); prev = f
    return out


def fit_sum(durs, total):
    durs = list(durs); delta = total - sum(durs); durs[-1] += delta
    i = len(durs) - 1
    while durs[i] < 0 and i > 0:
        durs[i - 1] += durs[i]; durs[i] = 0; i -= 1
    return durs


class Voice:
    def __init__(self, root: str | Path, vocoder: str | Path, providers=None):
        self.root = Path(root)
        prov = providers or (['CUDAExecutionProvider', 'CPUExecutionProvider'] if 'CUDAExecutionProvider' in ort.get_available_providers() else ['CPUExecutionProvider'])
        so = ort.SessionOptions(); so.log_severity_level = 3
        load = lambda p: ort.InferenceSession(str(p), so, providers=prov)
        self.cfg = yaml.safe_load((self.root / 'dsconfig.yaml').read_text())
        self.tokens = json.loads((self.root / self.cfg['phonemes']).read_text())
        sub = lambda d: yaml.safe_load((self.root / d / 'dsconfig.yaml').read_text())
        self.dur_cfg, self.pitch_cfg, self.var_cfg = sub('dsdur'), sub('dspitch'), sub('dsvariance')
        self.linguistic = load(self.root / 'dsdur' / self.dur_cfg['linguistic'])
        self.dur = load(self.root / 'dsdur' / self.dur_cfg['dur'])
        self.pitch = load(self.root / 'dspitch' / self.pitch_cfg['pitch'])
        self.variance = load(self.root / 'dsvariance' / self.var_cfg['variance'])
        self.acoustic = load(self.root / self.cfg['acoustic'])
        vdir = Path(vocoder)
        vcfg = yaml.safe_load((vdir / 'vocoder.yaml').read_text())
        self.vocoder = load(vdir / vcfg['model'])
        self.voc_mel_base = str(vcfg.get('mel_base', '10'))
        self.sr = self.cfg['sample_rate']
        self.frame_ms = 1000.0 * self.cfg['hop_size'] / self.sr

    def tok(self, ph):
        if ph not in self.tokens: raise KeyError(f'phoneme "{ph}" is not in this voice')
        return self.tokens[ph]

    # ---- timing: phonemes per note, anchored at vowels ----
    def layout(self, words: list[Word]):
        """-> phones [(phoneme, start_ms, end_ms)], phrase end ms. The duration model + OpenUtau's alignment."""
        fm = self.frame_ms
        first = words[0].notes[0]
        groups = [[first.start - PAD_MS, first.midi, ['SP']]]
        for w in words:
            sung = [n for i, n in enumerate(w.notes) if i not in w.holds]
            starts, ni = [], 0
            for i, ph in enumerate(w.phonemes):
                if ph in VOWELS:
                    starts.append(i - 1 if i >= 2 and w.phonemes[i - 1] in GLIDES and w.phonemes[i - 2] not in VOWELS else i)
            if not starts: starts = [0]
            starts = set(starts)
            for i, ph in enumerate(w.phonemes):
                if i in starts and ni < len(sung):
                    groups.append([sung[ni].start, sung[ni].midi, []]); ni += 1
                groups[-1][2].append(ph)
        last = words[-1].notes[-1]
        groups.append([last.start + last.dur, last.midi, []])
        phs = [p for g in groups for p in g[2]]
        tokens = np.array([[self.tok(p) for p in phs]], np.int64)
        word_div = np.array([[len(g[2]) for g in groups[:-1]]], np.int64)
        word_dur = np.array([[int(b[0] / fm) - int(a[0] / fm) for a, b in zip(groups, groups[1:])]], np.int64)
        enc, mask = self.linguistic.run(None, {'tokens': tokens, 'word_div': word_div, 'word_dur': word_dur})
        ph_midi = np.array([[int(round(g[1])) for g in groups for _ in g[2]]], np.int64)
        dur = self.dur.run(None, {'encoder_out': enc, 'x_masks': mask, 'ph_midi': ph_midi})[0][0].astype(float)
        counts = [len(g[2]) for g in groups]
        cum = np.cumsum(counts)
        align = list(zip(cum[:-1], [g[0] for g in groups[1:]]))          # (index of a group's first phoneme, its ms)

        def stretch(src, ratio, end):
            start = end - sum(src) * ratio
            return list(start + np.concatenate([[0], np.cumsum(np.array(src) * ratio)])[:-1])

        pos = stretch(list(dur[1:align[0][0]]), fm, align[0][1])       # leading consonants keep their own length
        for (i0, t0), (i1, t1) in zip(align, align[1:]):
            seg = list(dur[i0:i1])
            pos += stretch(seg, (t1 - t0) / max(sum(seg), 1e-6), t1)
        end = groups[-1][0]
        starts = [groups[0][0]] + pos
        phones = [(p, s, e) for p, s, e in zip(phs, starts, starts[1:] + [end])][1:]   # drop the leading SP
        return phones, end

    # ---- the padded frame layout every later model shares ----
    def segments(self, phones, end):
        fm = self.frame_ms
        segs = [('SP', HEAD * fm, False)]
        for i, (p, s, e) in enumerate(phones):
            if i and s - phones[i - 1][2] > 0: segs.append(('SP', s - phones[i - 1][2], False))
            segs.append((p, e - s, True))
        segs.append(('SP', TAIL * fm, False))
        durs = frames_from_ms([d for _, d, _ in segs], fm)
        return segs, durs

    def word_mode(self, segs, durs):
        vids = [i for i, (p, _, real) in enumerate(segs) if real and p in VOWELS] or [len(segs) - 2]
        div = [vids[0]] + [b - a for a, b in zip(vids, vids[1:])] + [len(segs) - vids[-1]]
        wd, o = [], 0
        for n in div: wd.append(sum(durs[o:o + n])); o += n
        return np.array([div], np.int64), np.array([wd], np.int64)

    def render_phrase(self, words: list[Word], steps=20, depth=None, pitch_steps=10, expr=1.0, correct=1.0, seed=0):
        """-> (audio float32 at self.sr, start_ms of audio[0], dict of curves)."""
        rng = np.random.default_rng(seed)
        fm = self.frame_ms
        phones, end = self.layout(words)
        segs, durs = self.segments(phones, end)
        total = sum(durs)
        t0 = phones[0][1] - HEAD * fm
        tokens = np.array([[self.tok(p) for p, _, _ in segs]], np.int64)
        div, wd = self.word_mode(segs, durs)
        enc, _ = self.linguistic.run(None, {'tokens': tokens, 'word_div': div, 'word_dur': wd})
        ph_dur = np.array([durs], np.int64)

        # notes for the pitch model: head rest, rests in gaps, the notes, tail rest
        notes = [n for w in words for n in w.notes]
        nd, nm, nr = [max(0.0, notes[0].start - t0)], [notes[0].midi], [True]
        prev = notes[0].start
        for n in notes:
            if n.start - prev > 0: nd.append(n.start - prev); nm.append(n.midi); nr.append(True)
            nd.append(n.dur); nm.append(n.midi); nr.append(False); prev = n.start + n.dur
        nd.append(TAIL * fm); nm.append(notes[-1].midi); nr.append(True)
        note_dur = fit_sum(frames_from_ms(nd, fm), total)
        pin = {'encoder_out': enc, 'ph_dur': ph_dur, 'note_midi': np.array([nm], np.float32),
               'note_rest': np.array([nr], bool), 'note_dur': np.array([note_dur], np.int64),
               'pitch': np.full((1, total), 60.0, np.float32), 'expr': np.full((1, total), expr, np.float32),
               'retake': np.ones((1, total), bool), 'steps': np.array(pitch_steps, np.int64)}
        pitch = self.pitch.run(None, {k: v for k, v in pin.items() if k in {i.name for i in self.pitch.get_inputs()}})[0][0]

        # Mortiflix correction layer: centre each sung note's middle 60% on its written note
        off = np.zeros(total)
        frame_of = lambda ms: int(np.clip((ms - t0) / fm, 0, total))
        for n in notes:
            a, b = frame_of(n.start), frame_of(n.start + n.dur)
            if b - a < 3: continue
            m0, m1 = a + int(0.2 * (b - a)), a + int(0.8 * (b - a))
            off[a:b] = correct * (n.midi - np.median(pitch[m0:m1]))
        k = max(1, int(30 / fm))
        off = np.convolve(np.pad(off, k, mode='edge'), np.ones(2 * k + 1) / (2 * k + 1), 'same')[k:-k]
        pitch = (pitch + off).astype(np.float32)

        vin = {'encoder_out': enc, 'ph_dur': ph_dur, 'pitch': pitch[None],
               'energy': np.zeros((1, total), np.float32), 'breathiness': np.zeros((1, total), np.float32),
               'voicing': np.zeros((1, total), np.float32), 'tension': np.zeros((1, total), np.float32),
               'retake': np.ones((1, total, 4), bool), 'steps': np.array(pitch_steps, np.int64)}
        energy, breath, voicing, tension = self.variance.run(None, vin)
        f0 = (440.0 * 2 ** ((pitch - 69) / 12)).astype(np.float32)
        ain = {'tokens': tokens, 'durations': ph_dur, 'f0': f0[None], 'energy': energy, 'breathiness': breath,
               'voicing': voicing, 'tension': tension, 'gender': np.zeros((1, total), np.float32),
               'velocity': np.ones((1, total), np.float32),
               'depth': np.array(float(depth if depth is not None else self.cfg.get('max_depth', 0.6)), np.float32),
               'steps': np.array(steps, np.int64)}
        mel = self.acoustic.run(None, {k: v for k, v in ain.items() if k in {i.name for i in self.acoustic.get_inputs()}})[0]
        if self.voc_mel_base != str(self.cfg.get('mel_base', '10')):
            mel = mel * (0.434294 if self.voc_mel_base == '10' else 2.30259)
        wav = self.vocoder.run(None, {'mel': mel.astype(np.float32), 'f0': f0[None]})[0][0]
        return wav.astype(np.float32), t0, {'pitch': pitch, 'f0': f0, 'phones': phones, 'frame_ms': fm}
