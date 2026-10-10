"""Forced alignment for sung takes: where every phoneme of a known line starts and ends.

A phoneme recognizer (wav2vec2 trained to write eSpeak IPA, facebook/wav2vec2-lv-60-espeak-cv-ft) gives per-frame
probabilities; torchaudio's CTC forced aligner finds the best path through exactly the expected phonemes. ARPAbet is
mapped to the recognizer's IPA symbols. Frames are 20 ms."""
from __future__ import annotations
import json
import numpy as np, torch, torchaudio
from scipy.signal import resample_poly

MODEL = 'facebook/wav2vec2-lv-60-espeak-cv-ft'
OFFSET_S = 0.044     # the recognizer fires ~44 ms after a sound starts (measured on labelled renders: median 16 ms after)
ARPA2IPA = {'aa': ['ɑː', 'ɑ'], 'ae': ['æ'], 'ah': ['ʌ', 'ə'], 'ao': ['ɔː', 'ɔ'], 'aw': ['aʊ'], 'ax': ['ə'], 'ay': ['aɪ'],
            'eh': ['ɛ'], 'er': ['ɚ', 'ɜː'], 'ey': ['eɪ'], 'ih': ['ɪ'], 'iy': ['iː', 'i'], 'ow': ['oʊ'], 'oy': ['ɔɪ'],
            'uh': ['ʊ'], 'uw': ['uː', 'u'], 'b': ['b'], 'ch': ['tʃ'], 'd': ['d'], 'dh': ['ð'], 'dx': ['ɾ'], 'f': ['f'],
            'g': ['ɡ'], 'hh': ['h'], 'jh': ['dʒ'], 'k': ['k'], 'l': ['l'], 'm': ['m'], 'n': ['n'], 'ng': ['ŋ'], 'p': ['p'],
            'r': ['ɹ'], 's': ['s'], 'sh': ['ʃ'], 't': ['t'], 'th': ['θ'], 'v': ['v'], 'w': ['w'], 'y': ['j'], 'z': ['z'], 'zh': ['ʒ']}


class Aligner:
    def __init__(self, device=None):
        from huggingface_hub import hf_hub_download
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.fe = Wav2Vec2FeatureExtractor.from_pretrained(MODEL)
        self.model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(self.device).eval()
        vocab = json.load(open(hf_hub_download(MODEL, 'vocab.json')))
        self.blank = vocab.get('<pad>', 0)
        self.ids = {}
        for a, cands in ARPA2IPA.items():
            tok = next((c for c in cands if c in vocab), None)
            if tok is None: raise KeyError(f'no recognizer symbol for {a}')
            self.ids[a] = vocab[tok]

    def emissions(self, y, sr):
        x = resample_poly(y, 16000, sr).astype(np.float32) if sr != 16000 else y.astype(np.float32)
        with torch.inference_mode():
            iv = self.fe(x, sampling_rate=16000, return_tensors='pt').input_values.to(self.device)
            return torch.log_softmax(self.model(iv).logits.float(), -1)      # 1 x frames x vocab, 20 ms frames

    def align(self, y, sr, phones: list[str]):
        """-> [(phone, start_s, end_s)] for the given ARPAbet phones (silences are not in the list)."""
        em = self.emissions(y, sr)
        tgt = torch.tensor([[self.ids[p] for p in phones]], dtype=torch.int32, device=em.device)
        path, scores = torchaudio.functional.forced_align(em, tgt, blank=self.blank)
        path = path[0].cpu().numpy()
        spans, k, prev = [], -1, self.blank
        for f, tok in enumerate(path):
            if tok != self.blank and (tok != prev or prev == self.blank):
                k += 1; spans.append([f, f + 1])
            elif tok != self.blank:
                spans[-1][1] = f + 1
            prev = tok
        if len(spans) != len(phones): raise RuntimeError(f'aligned {len(spans)} of {len(phones)} phonemes')
        # a phoneme lasts from its first frame until the next phoneme starts (CTC spans are peaky)
        out = []
        for i, (a, b) in enumerate(spans):
            end = spans[i + 1][0] if i + 1 < len(spans) else b
            out.append((phones[i], a * 0.02, max(end, b) * 0.02))
        # shift everything earlier by the measured lag, keeping order and the first start at >= 0
        return [(p, max(0.0, s0 - OFFSET_S), max(0.0, e0 - OFFSET_S)) for p, s0, e0 in out]
