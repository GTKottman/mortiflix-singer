#!/usr/bin/env python3
"""Export NVIDIA's BigVGAN v2 (MIT license, code and weights) to ONNX as an engine vocoder: mel [1, frames, 128]
(natural-log mel, 44.1 kHz, hop 512, fmin 0, fmax 22050) -> waveform [1, samples]. Voices trained with those mel
settings (train.py's default) sing through it, so nothing in the chain is non-commercial.

  export_bigvgan.py --out ~/MortiflixSinger/voices/bigvgan_v2 [--check some.wav]
Runs from trainer/.venv; uses ref/BigVGAN (git clone https://github.com/NVIDIA/BigVGAN, pinned in setup.sh)."""
import argparse, shutil, sys
from pathlib import Path
import numpy as np, torch, yaml

HERE = Path(__file__).parent
REPO = HERE.parent / 'ref' / 'BigVGAN'
MODEL = 'nvidia/bigvgan_v2_44khz_128band_512x'


class Wrapper(torch.nn.Module):
    def __init__(self, g):
        super().__init__(); self.g = g

    def forward(self, mel):                       # [1, frames, bins] as the engine's acoustic models give it
        return self.g(mel.transpose(1, 2)).squeeze(1)


def fix_for_onnx(g, h):
    """The anti-aliasing filters expand their kernel to the input's channel count at run time, which ONNX can't
    trace. Each filter module always sees the same channel count, so one pass records it and the expanded kernels
    become fixed buffers (same numbers, same output)."""
    import types
    import torch.nn.functional as F
    from alias_free_activation.torch.resample import UpSample1d
    from alias_free_activation.torch.filter import LowPassFilter1d
    seen = {}
    hooks = [m.register_forward_pre_hook(lambda m, inp: seen.__setitem__(m, inp[0].shape[1]))
             for m in g.modules() if isinstance(m, (UpSample1d, LowPassFilter1d))]
    with torch.no_grad(): g(torch.randn(1, h.num_mels, 16) - 5)
    for hk in hooks: hk.remove()

    def up(self, x):
        x = F.pad(x, (self.pad, self.pad), mode='replicate')
        x = self.ratio * F.conv_transpose1d(x, self.filter_full, stride=self.stride, groups=self.filter_full.shape[0])
        return x[..., self.pad_left:-self.pad_right]

    def low(self, x):
        if self.padding: x = F.pad(x, (self.pad_left, self.pad_right), mode=self.padding_mode)
        return F.conv1d(x, self.filter_full, stride=self.stride, groups=self.filter_full.shape[0])

    for m, c in seen.items():
        m.register_buffer('filter_full', m.filter.expand(c, -1, -1).contiguous())
        m.forward = types.MethodType(up if isinstance(m, UpSample1d) else low, m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True); ap.add_argument('--check', help='a WAV to resynthesize as a check')
    a = ap.parse_args()
    sys.path.insert(0, str(REPO))
    import bigvgan
    from meldataset import mel_spectrogram
    import json
    from huggingface_hub import hf_hub_download
    from env import AttrDict
    h = AttrDict(json.loads(Path(hf_hub_download(MODEL, 'config.json')).read_text()))
    g = bigvgan.BigVGAN(h, use_cuda_kernel=False)
    g.load_state_dict(torch.load(hf_hub_download(MODEL, 'bigvgan_generator.pt'), map_location='cpu', weights_only=True)['generator'])
    g.remove_weight_norm(); g.eval()
    h = g.h
    fix_for_onnx(g, h)
    out = Path(a.out).expanduser(); out.mkdir(parents=True, exist_ok=True)
    onnx_path = out / 'bigvgan_v2_44k_128band_512x.onnx'
    w = Wrapper(g).eval()
    dummy = torch.randn(1, 64, h.num_mels) - 5
    torch.onnx.export(w, (dummy,), str(onnx_path), input_names=['mel'], output_names=['waveform'],
                      dynamic_axes={'mel': {1: 'frames'}, 'waveform': {1: 'samples'}}, opset_version=17, dynamo=False)
    (out / 'vocoder.yaml').write_text(yaml.safe_dump({
        'name': 'bigvgan_v2_44k_128band_512x', 'model': onnx_path.name, 'num_mel_bins': h.num_mels, 'hop_size': h.hop_size,
        'win_size': h.win_size, 'fft_size': h.n_fft, 'sample_rate': h.sampling_rate, 'mel_fmin': 0, 'mel_fmax': h.sampling_rate // 2,
        'mel_base': 'e', 'pitch_controllable': False, 'license': 'MIT (NVIDIA BigVGAN v2)'}, sort_keys=False))
    shutil.copy2(REPO / 'LICENSE', out / 'LICENSE.txt')
    print(f'vocoder -> {out}')
    if a.check:
        import onnxruntime as ort, soundfile as sf
        from scipy.signal import resample_poly
        y, sr = sf.read(a.check, dtype='float32', always_2d=True); y = y.mean(1)
        if sr != h.sampling_rate: y = resample_poly(y, h.sampling_rate, sr).astype(np.float32)
        y = y[: h.sampling_rate * 8]
        mel = mel_spectrogram(torch.from_numpy(y)[None], h.n_fft, h.num_mels, h.sampling_rate, h.hop_size, h.win_size, h.fmin, h.fmax)
        sess = ort.InferenceSession(str(onnx_path), providers=['CPUExecutionProvider'])
        wav = sess.run(None, {'mel': mel.transpose(1, 2).numpy()})[0][0]
        with torch.no_grad(): ref = w(mel.transpose(1, 2))[0].numpy()
        n = min(len(wav), len(ref), len(y))
        mel2 = mel_spectrogram(torch.from_numpy(wav[:n])[None], h.n_fft, h.num_mels, h.sampling_rate, h.hop_size, h.win_size, h.fmin, h.fmax)
        m = min(mel.shape[-1], mel2.shape[-1])
        print(f'onnx vs torch max diff {np.abs(wav[:n] - ref[:n]).max():.2e}; resynthesis mel L1 {float((mel[..., :m] - mel2[..., :m]).abs().mean()):.3f}')
        sf.write(out / 'check-resynth.wav', wav[:n], h.sampling_rate)


if __name__ == '__main__':
    main()
