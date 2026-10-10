#!/usr/bin/env python3
"""A small, fast vocoder trained from scratch on your own recordings (BigVGAN's MIT trainer, a much smaller
generator than BigVGAN v2's 122 M parameters). Same mel settings as your voice (44.1 kHz, 128 bands, hop 512,
0-22050 Hz), so it can replace BigVGAN v2 for that voice. Nothing non-commercial goes into it.

  train_vocoder.py --data ~/MortiflixSinger/train/you --name you [--steps 200000] [--size small|medium] [--smoke]

Writes ~/MortiflixSinger/voices/<name>_vocoder/ (ONNX + vocoder.yaml); the voice uses it once its dsconfig says
`vocoder: <name>_vocoder` (train.py --vocoder own does that). Resumable: rerun the same command to continue."""
import argparse, json, math, os, random, subprocess
from pathlib import Path

HERE = Path(__file__).parent
BV = HERE.parent / 'ref' / 'BigVGAN'
PY = HERE / '.venv' / 'bin' / 'python'
SIZES = {'tiny': 128, 'small': 256, 'medium': 512}    # upsample_initial_channel, halved at each of 6 stages (BigVGAN v2: 1536)


def config(size, smoke):
    c = json.loads((BV / 'configs' / 'bigvgan_v2_44khz_128band_512x.json').read_text())
    c.update({'upsample_initial_channel': SIZES['tiny' if smoke else size], 'num_gpus': 0 if smoke else 1,
              'batch_size': 2 if smoke else 8, 'segment_size': 8192 if smoke else 32768, 'num_workers': 0 if smoke else 4,
              'fmin': 0, 'fmax': None, 'fmax_for_loss': None})
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True); ap.add_argument('--name', required=True)
    ap.add_argument('--steps', type=int, default=200000); ap.add_argument('--size', default='small', choices=['small', 'medium'])
    ap.add_argument('--smoke', action='store_true'); ap.add_argument('--export-only', action='store_true')
    ap.add_argument('--voices', default=str(Path.home() / 'MortiflixSinger' / 'voices'))
    a = ap.parse_args()
    data = Path(a.data).expanduser().resolve(); wavs = data / 'wavs'
    work = Path.home() / 'MortiflixSinger' / 'training' / f'{a.name}_vocoder'; work.mkdir(parents=True, exist_ok=True)
    names = sorted(f.stem for f in wavs.glob('*.wav'))
    if len(names) < 4: raise SystemExit('too few recordings for a vocoder')
    random.Random(0).shuffle(names); nval = max(1, len(names) // 20)
    (work / 'train.txt').write_text('\n'.join(f'{n}|' for n in names[nval:]) + '\n')
    (work / 'val.txt').write_text('\n'.join(f'{n}|' for n in names[:nval]) + '\n')
    cfg = config(a.size, a.smoke); (work / 'config.json').write_text(json.dumps(cfg, indent=1))
    steps = 20 if a.smoke else a.steps
    epochs = math.ceil(steps / max(1, (len(names) - nval) // cfg['batch_size']))
    if not a.export_only:
        cmd = [str(PY), 'train.py', '--config', str(work / 'config.json'), '--input_wavs_dir', str(wavs),
               '--input_training_file', str(work / 'train.txt'), '--input_validation_file', str(work / 'val.txt'),
               '--list_input_unseen_wavs_dir', str(wavs), '--list_input_unseen_validation_file', str(work / 'val.txt'),
               '--checkpoint_path', str(work / 'ckpt'), '--training_epochs', str(epochs),
               '--checkpoint_interval', str(min(5000, steps)), '--validation_interval', str(10 ** 9), '--debug', 'True']
        print('$', ' '.join(cmd), flush=True)
        with open(work / 'train.log', 'a') as log:
            r = subprocess.run(cmd, cwd=BV, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, 'PYTHONPATH': str(BV)})
        if r.returncode: raise SystemExit(f'training failed: see {work / "train.log"}')
    # export the newest generator checkpoint
    ckpts = sorted((work / 'ckpt').glob('g_*'))
    if not ckpts: raise SystemExit('no checkpoint yet')
    code = f'''
import sys, json, torch
sys.path.insert(0, {str(BV)!r}); sys.path.insert(0, {str(HERE)!r})
import bigvgan
from env import AttrDict
from export_bigvgan import export
from pathlib import Path
h = AttrDict(json.loads(Path({str(work / "config.json")!r}).read_text()))
g = bigvgan.BigVGAN(h, use_cuda_kernel=False)
g.load_state_dict(torch.load({str(ckpts[-1])!r}, map_location="cpu", weights_only=True)["generator"])
print(export(g, h, Path({str(Path(a.voices) / f"{a.name}_vocoder")!r}), {f"{a.name}_vocoder"!r}, "yours: trained from scratch on your recordings (BigVGAN code, MIT)"))
'''
    r = subprocess.run([str(PY), '-c', code], cwd=BV)
    if r.returncode: raise SystemExit('export failed')


if __name__ == '__main__':
    main()
