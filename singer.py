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


def save_project(a, notes, tokens, voice, transpose):
    """The sung part as a .msing project in ~/MortiflixSinger/projects (named by --save-project, or after the song)."""
    import json, os, re, mido
    name = a.save_project or ''
    if not name:                                  # Mortiflix Music: <project>/music/vocal/... with music/blueprint.json
        for d in Path(a.out).resolve().parents:
            bp = d / 'blueprint.json'
            if bp.exists(): name = json.loads(bp.read_text()).get('title', ''); break
    name = re.sub(r'[^\w .()-]', '', name or Path(a.midi).stem)[:80] or 'Sung'
    mf = mido.MidiFile(a.midi); bpm = 120.0
    for tr in mf.tracks:
        for m in tr:
            if m.type == 'set_tempo': bpm = round(mido.tempo2bpm(m.tempo), 3); break
        else: continue
        break
    ppq = 480; tick = lambda ms: round(ms / 1000 * bpm / 60 * ppq)
    ns = [{'id': f'n{i}', 'tick': tick(s0), 'dur': max(30, tick(s0 + d) - tick(s0)), 'pitch': int(p), 'lyric': (tokens[i] if i < len(tokens) else 'la'), 'vel': 64}
          for i, (s0, d, p) in enumerate(notes)]
    proj = {'version': 1, 'ppq': ppq, 'title': name, 'tempo': [{'tick': 0, 'bpm': bpm}], 'time_sig': [4, 4],
            'tracks': [{'id': 't1', 'name': 'Lead', 'voice': voice, 'mode': 'Default', 'mute': False, 'solo': False, 'gain_db': 0,
                        'pan': 0, 'transpose': transpose, 'notes': ns, 'lanes': {}, 'pitch_draw': [], 'params': {'expr': 1.0, 'correct': 1.0, 'steps': 20}}]}
    d = Path(os.environ.get('SINGER_HOME', Path.home() / 'MortiflixSinger')) / 'projects'; d.mkdir(parents=True, exist_ok=True)
    (d / f'{name}.msing').write_text(json.dumps(proj), encoding='utf-8')
    return name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--midi', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--lyrics'); ap.add_argument('--tags')
    ap.add_argument('--voice', default='SPORE'); ap.add_argument('--vocoder', help='a vocoder folder (default: the one the voice asks for)')
    ap.add_argument('--transpose', type=int); ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--channel', type=int, help='MIDI channel 1-16 (default: all)')
    ap.add_argument('--beats-per-bar', type=int, default=4, help='(accepted for robovox compatibility)')
    ap.add_argument('--save-project', nargs='?', const='', help='also save what was sung as a Singer project (name; default: '
                    'the song title from a nearby blueprint.json, Mortiflix Music\'s layout). With --tags this is on by default')
    ap.add_argument('--no-project', action='store_true')
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
    if (a.save_project is not None or a.tags) and not a.no_project:
        name = save_project(a, notes, tokens, vdir.name, tr)
        if name: print(f'saved as the Singer project "{name}" (open it in the editor to change the singing)')
    print(f'{len(notes)} notes, {sum(len(p) for p in phr)} words in {len(phr)} phrases, voice {vdir.name}{f", {tr:+d} semitones" if tr else ""} '
          f'-> {a.out} ({len(wav)/v.sr:.1f} s, {time.time()-t0:.1f} s to render)')


if __name__ == '__main__':
    main()
