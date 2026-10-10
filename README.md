# Mortiflix Singer

An open singing-voice synthesizer: write notes and lyrics (or bring a MIDI part), and it sings them with a human
voice, in tune and in time. Train your own voice with the built-in recording booth, made for people who can't sing in
tune. Runs on Windows, macOS and Linux; a VST3/CLAP/AU plugin brings it into your DAW.

**Status: early development.** Working today (Linux, developer preview):

- **Engine:** drives DiffSinger voice models: notes + words -> phonemes -> durations -> a natural pitch curve centred
  on every note -> breath and tension -> spectrogram -> audio. Breaths, vibrato, per-note dynamics and consonant timing.
- **Editor** (web): piano roll with words on the notes, pitch drawing, expression lanes (energy, breathiness, voicing,
  tension, gender, velocity), vocal modes, retakes, multiple tracks, checks (every word heard back, every note
  measured), import MIDI / UST / SVP / VSQX / MusicXML, export WAV / MIDI / MusicXML.
- **Booth** (web): 582 lines to record with a live tuner, graded for steadiness and clear words, never for being in tune.
- **Training:** Booth takes -> aligned, labelled dataset -> DiffSinger acoustic + variance models -> a voice the editor
  sings with. Proven end to end on a small test run; a real voice needs about an hour of takes and a graphics card.

## Try it (Linux, developer preview)

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python onnxruntime numpy soundfile scipy pyyaml g2p_en mido
# a DiffSinger voice package in voices/<name>/ and the OpenVPI NSF-HiFiGAN vocoder in voices/nsf_hifigan/
.venv/bin/python singer.py --midi part.mid --lyrics "Ride the light, feel the heat, chrome sun- rise now" --out vocal.wav
```

Lyrics: one token per note. `sun- rise` = one word over two notes, `_` holds a vowel onto the next note, `.` leaves a
note silent, `word{ph ph ph}` spells phonemes by hand.

## Train a voice

```bash
trainer/setup.sh                       # once: DiffSinger (pinned) + PyTorch in trainer/.venv
# record in the Booth, then on the Training page press Start, or by hand:
trainer/.venv/bin/python trainer/build_dataset.py --booth ~/MortiflixSinger/datasets/you --out ~/MortiflixSinger/train/you
trainer/.venv/bin/python trainer/train.py --data ~/MortiflixSinger/train/you --name you
```

The voice lands in `~/MortiflixSinger/voices/you` and shows up in the editor's voice list. `trainer/make_synthetic.py`
builds a labelled test set from an existing voice, for checking the pipeline (and the aligner) without recording.

## Plan

The full design (every component, the app, the plugin, the recording booth, training, licensing, build order) is in
[docs/DESIGN.md](docs/DESIGN.md).

## Credits

- [DiffSinger](https://github.com/openvpi/DiffSinger) (OpenVPI, Apache-2.0): the voice model architecture.
- [OpenUtau](https://github.com/stakira/OpenUtau) (MIT): reference for driving DiffSinger models.
- Voices are not included. Your own trained voice is yours; third-party voices keep their own licenses.
