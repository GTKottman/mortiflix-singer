"""The training kit for installed apps: everything trainer/setup.sh sets up in a checkout, done from the app.

~/MortiflixSinger/kit/
  trainer/ engine/ booth/script.json   the training sources (shipped inside the app)
  ref/DiffSinger/                       DiffSinger at the pinned commit (a zip from GitHub: no git needed)
  uv(.exe)                              Astral's uv (pinned), which also fetches the Python it needs
  trainer/.venv/                        Python 3.11 + PyTorch (+ CUDA when an NVIDIA card is present) + DiffSinger's deps

install(home, sources, progress) is idempotent: finished steps are skipped on a rerun."""
from __future__ import annotations
import io, os, platform, shutil, subprocess, sys, tarfile, urllib.request, zipfile
from pathlib import Path

UV_VERSION = '0.12.18'
DS_REV = 'ba031f6f2f969373b49a926cf8b007e9ae48834f'
BV_REV = '7d2b454564a6c7d014227f635b7423881f14bdac'      # BigVGAN (MIT): the own-vocoder stage
DEPS = ['soundfile', 'soxr', 'g2p_en', 'mido', 'onnxruntime', 'transformers', 'setuptools<81', 'pyworld', 'pyyaml',
        'auraloss', 'nnAudio', 'huggingface_hub']      # no pesq: source-only (needs a compiler); see train_vocoder.py


def kit_dir(home: Path) -> Path: return home / 'kit'


def python_of(home: Path) -> Path:
    v = kit_dir(home) / 'trainer' / '.venv'
    return v / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def ready(home: Path) -> bool:
    return python_of(home).exists() and (kit_dir(home) / 'ref' / 'DiffSinger' / 'scripts' / 'train.py').exists() and (kit_dir(home) / '.done').exists()


def _uv_asset():
    m, s = platform.machine().lower(), sys.platform
    arch = 'aarch64' if m in ('arm64', 'aarch64') else 'x86_64'
    if s.startswith('win'): return f'uv-{arch}-pc-windows-msvc.zip'
    if s == 'darwin': return f'uv-{arch}-apple-darwin.tar.gz'
    return f'uv-{arch}-unknown-linux-gnu.tar.gz'


def _get(url, progress, label):
    progress(label)
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def install(home: Path, sources: Path, progress=print):
    """sources: a folder holding trainer/, engine/ and booth/script.json (the app's bundled copy, or a checkout)."""
    k = kit_dir(home); k.mkdir(parents=True, exist_ok=True)
    # 1. the sources (always refreshed, so an app update brings the trainer along)
    for d in ('trainer', 'engine'):
        dst = k / d; dst.mkdir(exist_ok=True)
        for f in (sources / d).glob('*.py'): shutil.copy2(f, dst / f.name)
    (k / 'booth').mkdir(exist_ok=True); shutil.copy2(sources / 'booth' / 'script.json', k / 'booth' / 'script.json')
    # 2. uv
    uv = k / ('uv.exe' if os.name == 'nt' else 'uv')
    if not uv.exists():
        data = _get(f'https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{_uv_asset()}', progress, 'Downloading uv')
        name = 'uv.exe' if os.name == 'nt' else 'uv'
        if _uv_asset().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as z: uv.write_bytes(z.read(next(n for n in z.namelist() if n.endswith(name))))
        else:
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                m = next(x for x in t.getmembers() if x.name.endswith('/' + name) or x.name == name)
                uv.write_bytes(t.extractfile(m).read())
        uv.chmod(0o755)
    # 3. DiffSinger at the pinned commit
    ds = k / 'ref' / 'DiffSinger'
    if not (ds / 'scripts' / 'train.py').exists():
        data = _get(f'https://github.com/openvpi/DiffSinger/archive/{DS_REV}.zip', progress, 'Downloading DiffSinger')
        (k / 'ref').mkdir(exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = z.namelist()[0].split('/')[0]
            for n in z.namelist():
                if '..' in Path(n).parts: raise ValueError(f'unsafe path in the DiffSinger zip: {n}')
            z.extractall(k / 'ref')
        if ds.exists(): shutil.rmtree(ds)
        (k / 'ref' / root).rename(ds)
    bv = k / 'ref' / 'BigVGAN'
    if not (bv / 'train.py').exists():
        data = _get(f'https://github.com/NVIDIA/BigVGAN/archive/{BV_REV}.zip', progress, 'Downloading BigVGAN')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = z.namelist()[0].split('/')[0]
            if any('..' in Path(n).parts for n in z.namelist()): raise ValueError('unsafe path in the BigVGAN zip')
            z.extractall(k / 'ref')
        if bv.exists(): shutil.rmtree(bv)
        (k / 'ref' / root).rename(bv)
    # 4. Python + PyTorch + dependencies (uv fetches Python 3.11 itself)
    venv = k / 'trainer' / '.venv'
    run = lambda *a: subprocess.run([str(uv), *map(str, a)], check=True, cwd=k, env={**os.environ, 'PYTHONUTF8': '1'})
    if not python_of(home).exists():
        progress('Getting Python'); run('venv', '-q', '-p', '3.11', venv)
    if not (k / '.done').exists():
        # pyworld (pinned by DiffSinger) only ships Windows wheels, so Linux and macOS compile it: say so up front
        if os.name != 'nt' and not (shutil.which('c++') or shutil.which('g++') or shutil.which('clang++')):
            raise RuntimeError('a C++ compiler is needed once: on macOS run "xcode-select --install", on Linux install your '
                               'distribution\'s build tools (e.g. build-essential), then press Install again')
        gpu = shutil.which('nvidia-smi') is not None and sys.platform != 'darwin'
        progress('Installing PyTorch' + (' for your NVIDIA card' if gpu else ''))
        run('pip', 'install', '-q', '-p', python_of(home), 'torch', 'torchaudio', *(['--index-url', 'https://download.pytorch.org/whl/cu124'] if gpu else []))
        if os.name == 'nt':          # a fresh Windows lacks the Visual C++ runtime PyTorch needs: put it in the venv itself
            progress('Adding the Visual C++ runtime')
            run('pip', 'install', '-q', '-p', python_of(home), 'msvc-runtime')
            site = venv / 'Lib' / 'site-packages'
            (site / 'sitecustomize.py').write_text(
                '# Mortiflix Singer training kit: the Visual C++ runtime DLLs live in the venv (msvc-runtime)\n'
                'import os, sys\nif os.name == "nt":\n    os.add_dll_directory(sys.prefix)\n')
        progress('Installing the training libraries')
        run('pip', 'install', '-q', '-p', python_of(home), '-r', ds / 'requirements.txt', *DEPS)
        progress('Getting the pronunciation dictionary')
        subprocess.run([str(python_of(home)), '-c', "import nltk; [nltk.download(p, quiet=True) for p in ('averaged_perceptron_tagger_eng', 'averaged_perceptron_tagger', 'cmudict')]"], check=True)
        (k / '.done').write_text(UV_VERSION)
    progress('Ready')
    return k
