#!/usr/bin/env python3
"""Sing a MIDI part. Also the singer command Mortiflix Music runs (--midi --tags --out --voice).

  singer.py --midi part.mid --lyrics "Ride the light ..." --out vocal.wav [--voice SPORE] [--transpose N]
  singer.py --midi part.mid --tags tags.txt --out vocal.wav --voice ~/MortiflixSinger/voices/you

--lyrics: one token per note ("sun- rise" = one word over two notes, "_" holds, "." silent, "br" breath).
--tags: a tag sheet, one line per note "bar:beat  note  beats  word" (robovox / Mortiflix Music); '#' lines are comments.
--voice: a voice name or folder (default SPORE). --transpose: semitones (default: whole octaves toward the voice's range).
The WAV starts at the MIDI file's time 0, so it lines up with the song."""
import argparse, sys, time
from pathlib import Path
import numpy as np, soundfile as sf
sys.path.insert(0, str(Path(__file__).parent))
from engine.ds import Voice
from engine import song, voices


def tag_tokens(path):
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        parts = line.split(None, 3)
        out.append(parts[3].strip() if len(parts) == 4 else '.')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--midi', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--lyrics'); ap.add_argument('--tags')
    ap.add_argument('--voice', default='SPORE'); ap.add_argument('--vocoder', help='a vocoder folder (default: the one the voice asks for)')
    ap.add_argument('--transpose', type=int); ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--channel', type=int, help='MIDI channel 1-16 (default: all)')
    ap.add_argument('--beats-per-bar', type=int, default=4, help='(accepted for robovox compatibility)')
    a, _unknown = ap.parse_known_args()          # Mortiflix Music may pass options meant for other singers
    if not (a.lyrics or a.tags): ap.error('give --lyrics or --tags')
    tokens = tag_tokens(a.tags) if a.tags else [t for t in (Path(a.lyrics).read_text() if Path(a.lyrics).is_file() else a.lyrics).replace(',', ' ').split() if t]
    vdir = voices.find_voice(a.voice)
    if vdir is None:
        print(f'note: "{a.voice}" is not a Mortiflix Singer voice; singing with SPORE', file=sys.stderr)
        vdir = voices.find_voice('SPORE')
        if vdir is None: sys.exit('no voices installed: download one on the Singer home page')
    t0 = time.time()
    v = Voice(vdir, a.vocoder or voices.vocoder_dir(vdir))
    notes = song.read_midi(a.midi, None if a.channel is None else a.channel - 1)
    if not notes: sys.exit('no notes in that MIDI part')
    tr = a.transpose if a.transpose is not None else voices.octave_toward([n[2] for n in notes], voices.info(vdir).get('range'))
    if len(tokens) != len(notes): print(f'note: {len(tokens)} words for {len(notes)} notes; extra notes sing "la"', file=sys.stderr)
    wav, phr = song.render(v, notes, tokens, transpose=tr, steps=a.steps)
    peak = np.abs(wav).max() or 1
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    sf.write(a.out, (wav * (0.7 / peak)).astype(np.float32), v.sr, subtype='PCM_24')
    print(f'{len(notes)} notes, {sum(len(p) for p in phr)} words in {len(phr)} phrases, voice {vdir.name}{f", {tr:+d} semitones" if tr else ""} '
          f'-> {a.out} ({len(wav)/v.sr:.1f} s, {time.time()-t0:.1f} s to render)')


if __name__ == '__main__':
    main()
