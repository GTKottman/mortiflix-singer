#!/usr/bin/env python3
"""Build the singer service as one executable for the desktop app (PyInstaller), named the way Tauri wants its
sidecars: app/src-tauri/binaries/singer-service-<target triple>[.exe]. Run with the Python that has requirements.txt.

  python packaging/build_service.py
"""
import os, platform, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build' / 'service'


def triple():
    out = subprocess.run(['rustc', '-vV'], capture_output=True, text=True).stdout
    return next(l.split(': ')[1] for l in out.splitlines() if l.startswith('host: '))


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    nltk_dir = BUILD / 'nltk_data'
    import nltk
    # both tagger names: g2p_en asks for the old one with some nltk versions and downloads it at run time otherwise
    for pkg in ('averaged_perceptron_tagger_eng', 'averaged_perceptron_tagger', 'cmudict'):
        nltk.download(pkg, download_dir=str(nltk_dir), quiet=True)
    sep = ';' if os.name == 'nt' else ':'
    args = [sys.executable, '-m', 'PyInstaller.utils.cliutils.makespec', '--onefile', '--name', 'singer-service',
            '--specpath', str(BUILD),
            '--add-data', f'{ROOT / "booth" / "script.json"}{sep}booth',
            '--add-data', f'{nltk_dir}{sep}nltk_data',
            '--add-data', f'{ROOT / "scripts"}{sep}scripts',
            '--collect-data', 'g2p_en', '--collect-data', 'faster_whisper',
            '--collect-binaries', 'onnxruntime', '--collect-binaries', 'ctranslate2',
            '--hidden-import', 'engine.checks', '--hidden-import', 'engine.formats',
            '--exclude-module', 'torch', '--exclude-module', 'matplotlib', '--exclude-module', 'tkinter',
            str(ROOT / 'server.py')]
    subprocess.run(args, check=True, cwd=ROOT)
    # inflect (used by g2p_en for numbers) is checked at import by typeguard, which reads the module's source:
    # keep those .py files in the bundle, not only the compiled ones
    spec = BUILD / 'singer-service.spec'
    t = spec.read_text().replace('    optimize=', "    module_collection_mode={'inflect': 'pyz+py', 'typeguard': 'pyz+py'},\n    optimize=", 1)
    if 'module_collection_mode' not in t: raise SystemExit('could not patch the spec (PyInstaller changed its template)')
    spec.write_text(t)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', str(BUILD / 'dist'),
                    '--workpath', str(BUILD / 'work'), str(spec)], check=True, cwd=ROOT)
    exe = '.exe' if os.name == 'nt' else ''
    dest = ROOT / 'app' / 'src-tauri' / 'binaries' / f'singer-service-{triple()}{exe}'
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BUILD / 'dist' / f'singer-service{exe}', dest)
    print(f'{dest} ({dest.stat().st_size / 1e6:.0f} MB)')


if __name__ == '__main__':
    main()
