# Mortiflix Singer

An open singing-voice synthesizer: write notes and lyrics (or bring a MIDI part), and it sings them with a human
voice, in tune and in time. Train your own voice with the built-in recording booth, made for people who can't sing in
tune. Runs on Windows, macOS and Linux; a VST3/CLAP/AU plugin brings it into your DAW.

**New here? Read [the guide](docs/GUIDE.md).** **Status: early development, everything below works.** Where each Synthesizer V feature stands, with the test that
shows it: [docs/STATUS.md](docs/STATUS.md). Decisions made along the way: [docs/DECISIONS.md](docs/DECISIONS.md).

- **Editor:** piano roll with words on the notes; lyrics typed as a line; phonemes per note with draggable lengths;
  pitch drawing (snaps to the key), vibrato, glides, scoop and overshoot per note; lanes for energy, breathiness,
  voicing, tension, gender and velocity; vocal modes (yours too); separate pitch and tone retakes with every take kept;
  note groups; tempo and time-signature changes; loops and markers; a backing track to sing against; MIDI keyboard
  input; scripts; English, Latin, Spanish and Italian.
- **Checks:** every word heard back and every note measured, linked to the note.
- **Import / export:** MIDI (with lyrics), MusicXML, UTAU, Synthesizer V, Vocaloid (.vsqx, .vpr); WAV at 44.1/48 kHz.
- **Booth:** 582 lines to record with a live tuner, graded for steadiness and clear words, never for being in tune.
- **Training:** your Booth takes become your voice (and optionally your own fast vocoder), nothing non-commercial in it.
- **Tune:** put any sung vocal in tune, onto its MIDI or a key, without the chipmunk effect.
- **Desktop app** for Windows, macOS and Linux; **plugin** (VST3, CLAP, AU) that plays your vocals in time with the DAW.

## Install

Installers for Windows (.msi / .exe), macOS (.dmg) and Linux (.AppImage / .deb) are built by GitHub Actions on every
change (Actions tab, artifacts) and attached to releases. On first start the app offers the vocoder and a starter
voice (SPORE, non-commercial) from their makers' releases; your own trained voice needs nothing else.

## Try it from the command line (developer preview)

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt
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

## In your DAW (FL Studio, Logic, Ableton, Reaper...)

Put **Mortiflix Singer** (VST3, CLAP or AU) on an instrument track and pick a project: it plays that project's
rendered vocals in time with the DAW (match the DAW's tempo to the project's). Render in the editor and the plugin
picks up the new take within a second. *Open in the editor* jumps to the project; *Bounce to WAV* writes
`Documents/Mortiflix Singer/Vocal - <project>.wav` from bar 1. *Capture MIDI* records what you play into the track
and *Send to Singer* puts it in the editor's Inbox.

On a computer without a graphics card, set **Renders from** to the computer that renders, e.g.
`http://my-pc.tailnet.ts.net:4747` (Tailscale): the plugin fetches the renders from there and keeps a copy, so the
song still plays when that computer is off.

## Use it from Mortiflix Music

Mortiflix Music sings songs with vocals through any singer command that takes `--midi --tags --out --voice`:

```bash
mortiflix-music setup voice --singer "$PWD/.venv/bin/python $PWD/singer.py" --voice ~/MortiflixSinger/voices/you
```

## Use it from Claude

`mcp/singer_mcp.py` is an MCP server (sing a melody, import a file, set lyrics, render, check every word, export,
follow training): `claude mcp add singer -s user -- python3 $PWD/mcp/singer_mcp.py`.

## Plan

The full design (every component, the app, the plugin, the recording booth, training, licensing, build order) is in
[docs/DESIGN.md](docs/DESIGN.md).

## Credits

- [DiffSinger](https://github.com/openvpi/DiffSinger) (OpenVPI, Apache-2.0): the voice model architecture.
- [OpenUtau](https://github.com/stakira/OpenUtau) (MIT): reference for driving DiffSinger models.
- Voices are not included. Your own trained voice is yours; third-party voices keep their own licenses.
