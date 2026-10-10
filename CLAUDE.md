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
- `mcp/singer_mcp.py`: stdio MCP (registered as `singer`): sing, import_file, set_lyrics, set_track, render, check...

## Gotchas (verified)
- `/tmp` is a RAM tmpfs with a quota: put big temp files under `~/MortiflixSinger/tmp` (`TMPDIR=` for PyInstaller,
  cargo install `--target-dir`).
- SPORE and the OpenVPI NSF-HiFiGAN are non-commercial. Voices trained here use BigVGAN (MIT, fmin 0 / fmax 22050);
  BigVGAN is ~2x real time on this CPU.
- DiffSinger needs every dictionary phoneme in the data, including AP: takes need audible breaths.
- clap-validator fails 4 state checks on any nih-plug plugin (their own gain example too).
- The singer service is started by hand or by the MCP (`~/MortiflixSinger/service.pid`); restart it after server.py
  edits. Editor browser tests: browser-harness `BU_NAME=mfxlappy`, own tab only.

## Testing
`.venv/bin/python -m pytest -q tests` (about 8 s; trainer tests also run in `trainer/.venv`). Plugin:
`cd plugin && cargo test`. Real training runs take hours on the GPU: ask the owner first.
