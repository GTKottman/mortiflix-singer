#!/usr/bin/env python3
"""Train a voice from a dataset (wavs/ + transcriptions.csv from build_dataset.py) with DiffSinger, then export it as a
voice package the engine loads (the same layout as SPORE: acoustic + variance ONNX, dsconfig.yaml, phonemes.json).

  train.py --data ~/MortiflixSinger/train/you --name you [--steps 160000] [--smoke]

Stages (each resumable; rerun the same command to continue): configs -> binarize -> acoustic -> variance -> export.
--smoke trains tiny models for a few updates on CPU: it proves every stage runs, the voice it makes is noise.
Runs DiffSinger from ref/DiffSinger (Apache-2.0) in the trainer/.venv environment."""
import argparse, json, os, shutil, subprocess
from pathlib import Path
import yaml

HERE = Path(__file__).parent
DS = HERE.parent / 'ref' / 'DiffSinger'
PY = HERE / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
VOCODER = 'bigvgan_v2_44k_128band_512x'        # see export_bigvgan.py
PHONES = 'aa ae ah ao aw ax ay b ch d dh eh er ey f g hh ih iy jh k l m n ng ow oy p r s sh t th uh uw v w y z zh'.split()


def write_dictionary(path, data):
    """Labels are already phonemes, so each maps to itself. Only phonemes the recordings contain go in (DiffSinger
    needs every one covered); the ones missing are reported so the Booth can ask for lines that have them."""
    seen = set()
    for row in (data / 'transcriptions.csv').read_text().splitlines()[1:]:
        seen.update(row.split(',')[1].split())
    have = [p for p in PHONES if p in seen]
    path.write_text(''.join(f'{p}\t{p}\n' for p in have))
    return sorted(set(PHONES) - seen), 'AP' in seen


def common(data, work, name, smoke):
    test = sorted(l.split(',')[0] for l in (data / 'transcriptions.csv').read_text().splitlines()[1:])[:max(1, min(5, 2 if smoke else 5))]
    return {
        'dictionaries': {'en': str(work / 'dictionary-en.txt')}, 'extra_phonemes': [], 'merged_phoneme_groups': [],
        'datasets': [{'raw_data_dir': str(data), 'speaker': name, 'spk_id': 0, 'language': 'en', 'test_prefixes': test}],
        'binarization_args': {'num_workers': 0}, 'pe': 'parselmouth', 'hnsep': 'world',
        'use_lang_id': False, 'num_lang': 1, 'use_spk_id': False, 'num_spk': 1,
        'pl_trainer_accelerator': 'cpu' if smoke else 'auto', 'pl_trainer_devices': 1 if smoke else 'auto',
        'pl_trainer_precision': '32-true' if smoke else '16-mixed',
        'num_ckpt_keep': 3, 'num_valid_plots': 2 if smoke else 10,
    }


def acoustic_config(data, work, name, steps, smoke):
    c = {'base_config': [str(DS / 'configs/acoustic.yaml')], **common(data, work, name, smoke),
         'binary_data_dir': str(work / 'binary-acoustic'),
         'vocoder': 'NsfHifiGAN', 'vocoder_ckpt': str(work / 'vocoder/model.ckpt'), 'val_with_vocoder': False,
         # the mel range BigVGAN v2 (MIT) was trained on, so the voice sings through a vocoder anyone may use commercially
         'fmin': 0, 'fmax': 22050,
         # the editor's lanes: expression curves the acoustic model listens to, plus gender (key shift) and velocity
         'use_energy_embed': True, 'use_breathiness_embed': True, 'use_voicing_embed': True, 'use_tension_embed': True,
         'use_key_shift_embed': True, 'use_speed_embed': True,
         'augmentation_args': {'random_pitch_shifting': {'enabled': True, 'range': [-5., 5.], 'scale': 0.75},
                               'fixed_pitch_shifting': {'enabled': False, 'targets': [-5., 5.], 'scale': 0.5},
                               'random_time_stretching': {'enabled': True, 'range': [0.5, 2.], 'scale': 0.75}},
         'diffusion_type': 'reflow', 'use_shallow_diffusion': True, 'T_start': 0.4, 'T_start_infer': 0.4,
         'K_step': 300, 'K_step_infer': 300,
         'max_updates': steps, 'val_check_interval': 2000, 'permanent_ckpt_start': max(steps // 2, 1), 'permanent_ckpt_interval': 10000}
    if smoke:
        c.update({'hidden_size': 64, 'backbone_args': {'num_channels': 64, 'num_layers': 2, 'kernel_size': 31, 'dropout_rate': 0.0,
                                                        'use_conditioner_cache': True, 'glu_type': 'atanglu'},
                  'shallow_diffusion_args': {'train_aux_decoder': True, 'train_diffusion': True, 'val_gt_start': False,
                                             'aux_decoder_arch': 'convnext', 'aux_decoder_args': {'num_channels': 64, 'num_layers': 2, 'kernel_size': 7, 'dropout_rate': 0.1},
                                             'aux_decoder_grad': 0.1},
                  'max_batch_frames': 4000, 'max_batch_size': 4, 'val_check_interval': steps, 'augmentation_args': {
                      'random_pitch_shifting': {'enabled': False}, 'fixed_pitch_shifting': {'enabled': False}, 'random_time_stretching': {'enabled': False}}})
    return c


def variance_data(data, work):
    """The variance model learns timing and melody, so takes without a sung note (breaths) are left out of its copy
    of the dataset; the wavs are shared."""
    import csv
    out = work / 'variance-data'; out.mkdir(parents=True, exist_ok=True)
    if not (out / 'wavs').exists():
        try: (out / 'wavs').symlink_to(data / 'wavs', target_is_directory=True)
        except OSError: shutil.copytree(data / 'wavs', out / 'wavs')     # Windows without symlink rights
    rows = list(csv.DictReader(open(data / 'transcriptions.csv')))
    keep = [r for r in rows if any(n != 'rest' for n in r.get('note_seq', 'rest').split())]
    if not any('AP' in r['ph_seq'].split() for r in keep):
        raise SystemExit('no breath heard before any sung line: breathe in audibly before singing (the Booth\'s count-in)')
    with open(out / 'transcriptions.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(keep)
    return out


def variance_config(data, work, name, steps, smoke):
    data = variance_data(data, work)
    c = {'base_config': [str(DS / 'configs/variance.yaml')], **common(data, work, name, smoke),
         'binary_data_dir': str(work / 'binary-variance'),
         'predict_dur': True, 'predict_pitch': True,
         'predict_energy': True, 'predict_breathiness': True, 'predict_voicing': True, 'predict_tension': True,
         'use_melody_encoder': True, 'use_glide_embed': False,
         'max_updates': steps, 'val_check_interval': 2000, 'permanent_ckpt_start': max(steps // 2, 1), 'permanent_ckpt_interval': 10000}
    if smoke:
        c.update({'hidden_size': 64, 'dur_prediction_args': {'arch': 'resnet', 'hidden_size': 64, 'dropout': 0.1, 'num_layers': 2, 'kernel_size': 3,
                                                             'log_offset': 1.0, 'loss_type': 'mse', 'lambda_pdur_loss': 0.3, 'lambda_wdur_loss': 1.0, 'lambda_sdur_loss': 3.0},
                  'melody_encoder_args': {'hidden_size': 32, 'enc_layers': 2},
                  'pitch_prediction_args': {'pitd_norm_min': -8.0, 'pitd_norm_max': 8.0, 'pitd_clip_min': -12.0, 'pitd_clip_max': 12.0, 'repeat_bins': 16,
                                            'backbone_type': 'lynxnet2', 'backbone_args': {'num_layers': 2, 'num_channels': 64, 'dropout_rate': 0.0,
                                                                                           'use_conditioner_cache': True, 'glu_type': 'atanglu'}},
                  'variances_prediction_args': {'total_repeat_bins': 16, 'backbone_type': 'lynxnet2',
                                                'backbone_args': {'num_layers': 2, 'num_channels': 64, 'dropout_rate': 0.0, 'use_conditioner_cache': True, 'glu_type': 'atanglu'}},
                  'max_batch_frames': 4000, 'max_batch_size': 4, 'val_check_interval': steps})
    return c


def run(args, log):
    env = dict(os.environ, PYTHONPATH=str(DS))
    print('$', ' '.join(map(str, args)), flush=True)
    with open(log, 'a') as f:
        p = subprocess.run([str(PY), *map(str, args)], cwd=DS, env=env, stdout=f, stderr=subprocess.STDOUT)
    if p.returncode: raise SystemExit(f'failed ({p.returncode}); see {log}')


def sung_range(data):
    """The lowest and highest notes in the recordings (10th/90th percentile), so the singer can place melodies."""
    import csv
    import numpy as np
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    ms = [names.index(n[:-1]) + 12 * (int(n[-1]) + 1) for r in csv.DictReader(open(data / 'transcriptions.csv'))
          for n in r.get('note_seq', '').split() if n != 'rest' and n[-1].isdigit()]
    if not ms: return None
    lo, hi = (int(round(x)) for x in np.percentile(ms, [10, 90]))
    return [f'{names[lo % 12]}{lo // 12 - 1}', f'{names[hi % 12]}{hi // 12 - 1}']


def package(work, name, out, data=None, vocoder=VOCODER):
    """DiffSinger's two export folders -> one voice folder in the engine's layout (SPORE's)."""
    out.mkdir(parents=True, exist_ok=True)
    a, v = work / 'export-acoustic', work / 'export-variance'
    for f in a.iterdir(): shutil.copy2(f, out / f.name)
    # one variance export holds the duration, pitch and expression models; the engine looks for each in its own
    # folder (SPORE's layout), so all three folders get the same files (hard links, no extra space)
    for d in ('dsdur', 'dspitch', 'dsvariance'):
        (out / d).mkdir(exist_ok=True)
        for f in v.iterdir():
            dst = out / d / f.name
            if dst.exists(): dst.unlink()
            try: os.link(f, dst)
            except OSError: shutil.copy2(f, dst)
    shutil.copy2(work / 'dictionary-en.txt', out / 'dictionary-en.txt')
    (out / 'character.yaml').write_text(yaml.safe_dump({'name': name, 'text_file_encoding': 'utf-8', 'range': sung_range(data) if data else None,
                                                        'license': 'yours: trained on your own recordings', 'commercial': True}))
    cfg = yaml.safe_load((out / 'dsconfig.yaml').read_text())
    cfg['vocoder'] = vocoder
    (out / 'dsconfig.yaml').write_text(yaml.safe_dump(cfg, sort_keys=False))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True); ap.add_argument('--name', required=True)
    ap.add_argument('--work', help='default: ~/MortiflixSinger/training/<name>')
    ap.add_argument('--steps', type=int, default=160000); ap.add_argument('--variance-steps', type=int)
    ap.add_argument('--smoke', action='store_true'); ap.add_argument('--only', choices=['configs', 'binarize', 'acoustic', 'variance', 'export'])
    ap.add_argument('--voices', default=str(Path.home() / 'MortiflixSinger' / 'voices'))
    ap.add_argument('--vocoder', default='bigvgan', choices=['bigvgan', 'own'],
                    help="own = the voice's own small vocoder from train_vocoder.py (fast on a CPU); bigvgan = BigVGAN v2")
    a = ap.parse_args()
    data = Path(a.data).expanduser().resolve()
    work = Path(a.work or Path.home() / 'MortiflixSinger' / 'training' / a.name).expanduser().resolve(); work.mkdir(parents=True, exist_ok=True)
    steps = 20 if a.smoke else a.steps; vsteps = 20 if a.smoke else (a.variance_steps or a.steps // 2)
    log = work / 'train.log'
    stages = [a.only] if a.only else ['configs', 'binarize', 'acoustic', 'variance', 'export']
    exp_a, exp_v = f'{a.name}_acoustic', f'{a.name}_variance'
    ca, cv = work / 'acoustic.yaml', work / 'variance.yaml'
    state_f = work / 'state.json'; state = json.loads(state_f.read_text()) if state_f.exists() else {}
    save = lambda: state_f.write_text(json.dumps(state, indent=1))
    if 'configs' in stages:
        missing, breaths = write_dictionary(work / 'dictionary-en.txt', data)
        if missing: print(f'not in the recordings (the voice will not say them): {" ".join(missing)}')
        if not breaths: raise SystemExit('the recordings need at least one breath (AP): record the in-breath lines')
        ca.write_text(yaml.safe_dump(acoustic_config(data, work, a.name, steps, a.smoke), sort_keys=False))
        cv.write_text(yaml.safe_dump(variance_config(data, work, a.name, vsteps, a.smoke), sort_keys=False))
        state['configs'] = True; save()
    if 'binarize' in stages:
        run(['scripts/binarize.py', '--config', ca], log); run(['scripts/binarize.py', '--config', cv], log)
        state['binarize'] = True; save()
    ckpt = work / 'checkpoints'
    for stage, cfg, exp in (('acoustic', ca, exp_a), ('variance', cv, exp_v)):
        # DiffSinger writes checkpoints/<exp> under its own folder; that path links to this voice's training folder
        mine, theirs = ckpt / exp, DS / 'checkpoints' / exp
        mine.mkdir(parents=True, exist_ok=True); theirs.parent.mkdir(exist_ok=True)
        if theirs.is_dir() and not theirs.is_symlink():
            for f in theirs.iterdir(): shutil.move(str(f), mine / f.name)
            theirs.rmdir()
        if not theirs.exists():
            try: theirs.symlink_to(mine)
            except OSError: mine = theirs; mine.mkdir(parents=True, exist_ok=True)   # Windows: keep them in DiffSinger's folder
        if stage in stages:
            run(['scripts/train.py', '--config', cfg, '--exp_name', exp, *([] if any(mine.glob('*.ckpt')) else ['--reset'])], log)
            state[stage] = True; save()
    if 'export' in stages:
        run([str(HERE / 'ds_export.py'), 'acoustic', '--exp', exp_a, '--out', work / 'export-acoustic'], log)
        run([str(HERE / 'ds_export.py'), 'variance', '--exp', exp_v, '--out', work / 'export-variance'], log)
        out = package(work, a.name, Path(a.voices) / a.name, data, f'{a.name}_vocoder' if a.vocoder == 'own' else VOCODER)
        state['export'] = str(out); save()
        print(f'voice -> {out}')


if __name__ == '__main__':
    main()
