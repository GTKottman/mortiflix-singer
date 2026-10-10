"""Finding voices and the vocoder each one asks for: the same rules for the service, the CLI and the MCP.

Voices live in ~/MortiflixSinger/voices (downloaded or trained) and the checkout's voices/ (development). A voice is
a folder with dsconfig.yaml; its 'vocoder:' names the vocoder (default: the OpenVPI NSF-HiFiGAN in nsf_hifigan/)."""
from __future__ import annotations
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
KNOWN = {'SPORE': {'range': ['F#3', 'G4'], 'license': 'CC BY-NC-ND 4.0: non-commercial use only, credit Knoxstation', 'commercial': False}}
NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def homes(home: Path | None = None):
    home = home or Path(os.environ.get('SINGER_HOME', Path.home() / 'MortiflixSinger'))
    return [home / 'voices', ROOT / 'voices']


def voice_dirs(home=None):
    found = {}
    for base in homes(home):
        if not base.exists(): continue
        for top, dirs, files in os.walk(base, followlinks=True):
            if 'dsconfig.yaml' not in files: continue
            d = Path(top)
            if d.name in ('dsdur', 'dspitch', 'dsvariance'): continue
            found.setdefault(d.name, d)
    return found


def find_voice(name_or_path, home=None):
    """A voice folder from a name ('SPORE', 'you') or a path (the voice folder or a parent holding exactly one)."""
    p = Path(str(name_or_path)).expanduser()
    if p.is_dir():
        if (p / 'dsconfig.yaml').exists(): return p
        inner = [Path(t) for t, _, f in os.walk(p, followlinks=True) if 'dsconfig.yaml' in f and Path(t).name not in ('dsdur', 'dspitch', 'dsvariance')]
        if len(inner) == 1: return inner[0]
    return voice_dirs(home).get(str(name_or_path))


def vocoder_dir(voice_dir, home=None):
    want = (yaml.safe_load((Path(voice_dir) / 'dsconfig.yaml').read_text()) or {}).get('vocoder') or 'nsf_hifigan'
    for base in homes(home):
        if not base.exists(): continue
        for y in base.glob('*/vocoder.yaml'):
            name = (yaml.safe_load(y.read_text()) or {}).get('name', '')
            if want in (y.parent.name, name) or (want == 'nsf_hifigan' and y.parent.name == 'nsf_hifigan'): return y.parent
    raise FileNotFoundError(f'no vocoder "{want}": install it on the Singer home page (Voices)')


def midi_of(name):
    n = name[:-1].upper(); o = int(name[-1])
    return NAMES.index(n) + 12 * (o + 1)


def info(voice_dir):
    """{'range': ['F#3', 'G4'] or None, 'license': ..., 'commercial': ...} from what we know or the voice's character.yaml."""
    d = Path(voice_dir)
    if d.name in KNOWN: return dict(KNOWN[d.name])
    ch = d / 'character.yaml'
    c = (yaml.safe_load(ch.read_text()) or {}) if ch.exists() else {}
    return {'range': c.get('range'), 'license': c.get('license', 'see the voice folder'), 'commercial': c.get('commercial')}


def octave_toward(notes_midi, rng):
    """Whole octaves that move a melody's median closest to the middle of the voice's range (0 when unknown)."""
    if not rng or not len(notes_midi): return 0
    import numpy as np
    lo, hi = midi_of(rng[0]), midi_of(rng[1])
    med = float(np.median(notes_midi)); mid = (lo + hi) / 2
    return int(round((mid - med) / 12)) * 12
