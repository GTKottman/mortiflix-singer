#!/usr/bin/env python3
"""singer.py --midi part.mid --lyrics "Ride the light ..." --out vocal.wav [--voice voices/SPORE/SPORE] [--transpose N]"""
import argparse, sys, time
from pathlib import Path
import numpy as np, soundfile as sf
sys.path.insert(0, str(Path(__file__).parent))
from engine.ds import Voice
from engine import song

ap = argparse.ArgumentParser()
ap.add_argument('--midi', required=True); ap.add_argument('--lyrics', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--voice', default=str(Path(__file__).parent / 'voices/SPORE/SPORE'))
ap.add_argument('--vocoder', default=str(Path(__file__).parent / 'voices/nsf_hifigan'))
ap.add_argument('--transpose', type=int, default=0); ap.add_argument('--steps', type=int, default=20)
ap.add_argument('--channel', type=int)
a = ap.parse_args()
text = Path(a.lyrics).read_text() if Path(a.lyrics).is_file() else a.lyrics
tokens = [t for t in text.replace(',', ' ').split() if t]
t0 = time.time()
v = Voice(a.voice, a.vocoder)
notes = song.read_midi(a.midi, None if a.channel is None else a.channel - 1)
wav, phr = song.render(v, notes, tokens, transpose=a.transpose, steps=a.steps)
peak = np.abs(wav).max() or 1
sf.write(a.out, (wav * (0.7 / peak)).astype(np.float32), v.sr, subtype='PCM_24')
print(f'{len(notes)} notes, {sum(len(p) for p in phr)} words in {len(phr)} phrases -> {a.out} ({len(wav)/v.sr:.1f} s, {time.time()-t0:.1f} s to render)')
