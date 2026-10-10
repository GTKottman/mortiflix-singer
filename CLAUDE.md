# Mortiflix Singer: notes for Claude

Open singing voice synthesizer (Synthesizer V / ACE Studio class) with a recording Booth and training for your own
voice. Public: github.com/GTKottman/mortiflix-singer (AGPL-3.0; plugin/ GPL-3.0-or-later). Default branch `master`.
Every default decision made without the owner goes in `docs/DECISIONS.md`. The design doc is `docs/DESIGN.md`.

## Layout
- `engine/ds.py`: DiffSinger ONNX driver (port of OpenUtau's method). `Voice.render_phrase(words, ...)`; notes carry
  vibrato, energy, `lead` (consonant lead-in), `glide`/`glide_offset`; lyric `br` = breath (AP). Our pitch layer
  centres each note's middle 60% on the written pitch. Vocoders with no `f0` input (BigVGAN) get only the mel.
- `engine/song.py` (lyric tokens -> words), `engine/project.py` (.msing projects, tempo map, cached phrase renders,
  vocal modes + `mode_strength`, retakes keyed by phrase first tick), `engine/formats.py` (MIDI/UST/SVP/VSQX/MusicXML),
  `engine/checks.py` (Whisper diction per phrase + tuning per note).
- `server.py`: the service. UNIX socket `~/MortiflixSinger/singer.sock` (dev; Mortiflix Music :4747 proxies
  `/api/singer/*` and serves `web/` at `/singer/`), `--stdio` framed HTTP (desktop app), `--port` (Windows dev).
  Writes `<project>.mix.json` on named final renders (the plugin plays it). Downloads voices/vocoders from official
  releases. Runs training jobs (own process group, stop by PID).
- `web/`: home (`index.html`), editor (`editor.html` + `editor/*.js`, scripting API `window.singer`), Booth, Training.
  CSP: no inline scripts/styles/handlers. POSTs need header `x-mortiflix: 1`.
- `booth/`: script (582 lines, sets A-G), grading (steadiness + clear words; pitch accuracy never lowers a grade).
- `trainer/`: `setup.sh` (pins DiffSinger + BigVGAN, own venv `trainer/.venv`), `align.py` (wav2vec2 phoneme CTC,
  44 ms lag removed), `build_dataset.py` (Booth -> DiffSinger CSV; notes from what was sung; breaths detected),
  `train.py` (configs, binarize, train, export, package; `--smoke` = tiny CPU run), `make_synthetic.py` (labelled
  test set from an existing voice), `export_bigvgan.py` (MIT vocoder -> ONNX, release asset `vocoder-bigvgan-v2`).
- `app/src-tauri/`: Tauri v2 desktop app; `singer://` protocol serves `web/` and forwards the API to the bundled
  service (`packaging/build_service.py`, PyInstaller). Built in CI (`.github/workflows/desktop.yml`).
- `plugin/`: nih-plug VST3/CLAP bridge (plays the mix file at the host's beat position; MIDI capture -> inbox).
  `cargo xtask bundle mortiflix_singer_bridge --release`; Windows: `./build-windows.sh`.
- `mcp/singer_mcp.py`: stdio MCP (registered as `singer`): sing, import_file, set_lyrics, set_track, render, check,
  export, tune, bridge, training.
- More engine pieces: `engine/correct.py` (WORLD pitch corrector, the Tune page; never moves octaves),
  `engine/lang_la.py` / `engine/lang_rules.py` (Latin, Spanish, Italian by rule; track `lang`), `engine/voices.py`
  (voice/vocoder lookup shared by service, CLI, MCP), `expand_groups` in project.py (note groups -> notes before
  render/check/export), tone takes (`tone_takes`, same pitch curve), per-note scoop/overshoot, `ph_scale`.
- Service extras: `/tune*`, `/bridge` (robovox s2s.py SoulX SVC into the owner's voice), `/backing`, `/inbox`
  (plugin MIDI capture), `/scripts` (bundled `scripts/*.js` + `~/MortiflixSinger/scripts`), `/train/kit`.
- `trainer/kit.py`: the desktop app's one-button training environment in `~/MortiflixSinger/kit` (uv, Python 3.11,
  PyTorch, DiffSinger + BigVGAN zips at pinned commits). `trainer/train_vocoder.py`: small own vocoder (3.6 M params).
- `plugin/au/`: AUv2 via clap-wrapper (CLAP embedded); built and auval-checked in the macOS CI job.
- `docs/STATUS.md`: every definition-of-done item with its evidence. Keep it current.

## Gotchas (verified)
- `/tmp` is a RAM tmpfs with a quota: put big temp files under `~/MortiflixSinger/tmp` (`TMPDIR=` for PyInstaller,
  cargo install `--target-dir`).
- SPORE and the OpenVPI NSF-HiFiGAN are non-commercial. Voices trained here use BigVGAN (MIT, fmin 0 / fmax 22050);
  BigVGAN is ~2x real time on this CPU.
- DiffSinger needs every dictionary phoneme in the data, including AP: takes need audible breaths.
- clap-validator fails 4 state checks on any nih-plug plugin (their own gain example too).
- The singer service is started by hand or by the MCP (`~/MortiflixSinger/service.pid`); restart it after server.py
  edits. A training job survives a restart (own process group); the service re-finds it from `training/<name>/job.pid`.
- Browser tests of the roll: CDP mouse input times out on a background tab; dispatch MouseEvents in the page instead
  (`singer.roll` is exposed). Playback can't start without a user gesture, so test players by their state, not sound. Editor browser tests: browser-harness `BU_NAME=mfxlappy`, own tab only.

- Windows training (proven on the test VM, see memory windows-test-vm): pesq has no wheels (kept out of the kit, stubbed
  for BigVGAN), a fresh Windows lacks the VC++ runtime (msvc-runtime + sitecustomize add_dll_directory), text defaults
  to cp1252 (service built in UTF-8 mode, jobs get PYTHONUTF8). SSH sessions kill child processes on Windows: run long
  VM tests as a scheduled task (/IT) and poll a log file.
- DiffSinger's default batches OOM on a 10 GB card; train.py fits batches + accumulates (fit_memory). Checkpoints are
  only written at validation points (val_check_interval = min(2000, steps)).
- Release: `git tag vX.Y.Z && git push origin vX.Y.Z` -> both workflows attach to a *draft* release; the owner publishes.

## Testing
`.venv/bin/python -m pytest -q tests` (about 8 s; trainer tests also run in `trainer/.venv`). Plugin:
`cd plugin && cargo test`. Real training runs take hours on the GPU: ask the owner first.
