# Mortiflix Singer

An open singing-voice synthesizer: write notes and lyrics (or bring a MIDI part), and it sings them with a human
voice, in tune and in time. Train your own voice with the built-in recording booth, made for people who can't sing in
tune. Runs on Windows, macOS and Linux; a VST3/CLAP/AU plugin brings it into your DAW.

**Status: early development (milestone M0).** The render engine drives DiffSinger voice models: notes + words ->
phonemes -> durations -> a natural pitch curve centred on every note -> breath and tension -> spectrogram -> audio.

## Try it (Linux, developer preview)

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python onnxruntime numpy soundfile scipy pyyaml g2p_en mido
# a DiffSinger voice package in voices/<name>/ and the OpenVPI NSF-HiFiGAN vocoder in voices/nsf_hifigan/
.venv/bin/python singer.py --midi part.mid --lyrics "Ride the light, feel the heat, chrome sun- rise now" --out vocal.wav
```

Lyrics: one token per note. `sun- rise` = one word over two notes, `_` holds a vowel onto the next note, `.` leaves a
note silent, `word{ph ph ph}` spells phonemes by hand.

## Plan

The full design (every component, the app, the plugin, the recording booth, training, licensing, build order) is in
[docs/DESIGN.md](docs/DESIGN.md).

## Credits

- [DiffSinger](https://github.com/openvpi/DiffSinger) (OpenVPI, Apache-2.0): the voice model architecture.
- [OpenUtau](https://github.com/stakira/OpenUtau) (MIT): reference for driving DiffSinger models.
- Voices are not included. Your own trained voice is yours; third-party voices keep their own licenses.
