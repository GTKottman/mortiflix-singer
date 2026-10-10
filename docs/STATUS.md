# Status against the definition of done (design doc section 1b)

Updated 2026-10-10. ✅ built and tested · 🟡 partly · ❌ not yet. "Tested" names the test or the check that was run.

## Editing

| Item | | Notes |
| --- | --- | --- |
| Piano roll, words on notes, multiple tracks | ✅ | browser-tested (render, pitch line, phonemes under notes) |
| Tempo changes | ✅ | any bar; renders follow (phrase end moved 4.3 → 4.8 s at 90 BPM) |
| Time-signature changes | ✅ | ruler, grid, bar positions; MIDI and MusicXML round trip (`test_meter_changes_survive_midi_and_musicxml`) |
| Loops, markers | ✅ | shift-drag the ruler, `L`; markers with `;`, click to jump |
| Lyric entry: a line onto notes, per-note edit, syllable fit shown | ✅ | lyric line flows onto selected notes; red notes = more syllables than notes |
| Phoneme editing per note; phoneme timing panel with draggable boundaries | ✅ | hand phonemes, a % per phoneme, boundaries dragged in the roll (in-page mouse test) |
| Note groups | ✅ | make (G), copy, move, transpose, edit once (every copy follows), ungroup; `test_note_groups_expand_to_notes` |
| Import MIDI (lyrics), MusicXML, UST, SVP, VSQX, VPR; export MIDI, MusicXML | ✅ | `tests/test_formats.py` |
| Unlimited undo/redo, autosave, recovery | ✅ | browser autosave; projects saved in `~/MortiflixSinger/projects` |

## Voice control

| Item | | Notes |
| --- | --- | --- |
| AI pitch with an expressiveness amount; manual pitch drawing | ✅ | Expression slider, Pitch tool |
| Vibrato, transition (glide), scoop, overshoot per note | ✅ | `test_glide_sets_the_slide_length`; scoop/overshoot curves checked |
| Snap to scale | ✅ | key/scale highlight; with a key set the Pitch tool snaps to the scale (Alt = free); the Tune tool snaps audio to a key |
| Retakes of pitch and tone per phrase, A/B between takes | ✅ | `test_tone_retake_keeps_the_pitch`; all takes cached and selectable (timing retakes: the duration model is deterministic, so a pitch take is the timing take) |
| Lanes: tension, breathiness, voicing, energy, gender, velocity | ✅ | mouth opening: no open model exposes it |
| Vocal modes, user-defined, with strength | ✅ | built-in six + your own (Song panel) |
| Duration and strength per note | ✅ | phoneme lengths, velocity |
| Cross-lingual | 🟡 | English, Latin, Spanish, Italian, Japanese (kana or romaji) (rule files, per track); more languages = more rule files; the voices are English, so foreign sounds use the nearest English ones |
| Breaths (auto and manual) | ✅ | `br` notes; "Breaths before phrases" script |

## Sound and output

| Item | | Notes |
| --- | --- | --- |
| Playback while editing, background rendering, preview vs final | ✅ | guide tones for unrendered notes; preview 8 steps, final 20 |
| Export WAV per track or mixed, 44.1/48 kHz, 16/24/32-bit | ✅ | 48 kHz/24-bit export checked in the browser |
| Plugin VST3 + CLAP on Windows/macOS/Linux, synced to the host | ✅ | CI builds all three; loader test against a real render; clap-validator 32/44 (the 4 failures are nih-plug's own, its example plugin fails the same) |
| AU on macOS | ✅ | clap-wrapper (MIT) wraps the CLAP as an AUv2 with the CLAP inside; CI builds it and Apple's auval passes |
| Standalone app on all three systems | ✅ | CI installers; the Windows installer was installed and run on a Windows 11 VM (editor rendered) |

## Automation

| Item | | Notes |
| --- | --- | --- |
| Scripting API (JavaScript) | ✅ | `window.singer` + Scripts menu (bundled + `~/MortiflixSinger/scripts`) |
| Command line, HTTP API, MCP tools | ✅ | `singer.py`, the service ([docs/API.md](API.md)), `mcp/singer_mcp.py` (registered as `singer`) |

## Beyond Synthesizer V

| Item | | Notes |
| --- | --- | --- |
| Train your own voice (Booth, live tuner, tone-deaf-first, one-button training) | 🟡 | the Booth follows the four sit-down sessions, reminds you to rest every 10 minutes or when takes get rougher, adds lines from your own songs (set D), and shows "Build my voice" once there is enough; every stage proven on a test set (Booth takes → dataset → models → a voice that sings); a real voice needs your recordings and hours of GPU (batches are fitted to the card: the defaults ran out of memory on the 3080, now fixed). The desktop app installs its training kit with one button (uv, Python, PyTorch, DiffSinger). Proven on a fresh Windows 11 VM: kit installed by the app, then a test session trained into a voice (24 min on CPU, smoke size) after fixing what that run found (no compiler for pesq, missing Visual C++ runtime, cp1252 text) |
| Commercial-clean output for your voice | ✅ | trained voices use BigVGAN v2 (MIT); slow on CPU (about 2x real time), fast on a GPU |
| Diction, tuning and timing checks on every render | ✅ | Check button / MCP `check`; "Fix unclear words" tries new takes of each unclear phrase and keeps the clearest (Undertow: 35 → 28 unclear of 149) |
| Pitch corrector for any vocal WAV | ✅ | Tune page; real vocal 14 → 1 cents typical |
| Mortiflix Music integration | 🟡 | `singer.py` speaks its singer interface; switching your configured singer waits for your trained voice |
| Bridge into your voice before your model exists | ✅ | Export → "WAV in my voice" (robovox SoulX SVC); words get smudged by the conversion |

## Known gaps worth doing next

- Record in the Booth (about an hour of kept takes) and train the first real voice.
- Train the optional own vocoder with your recordings (the code is ready and smoke-tested; 3.6 M parameters, about 11x faster than BigVGAN v2 on a CPU).
- More languages; a Logic test by hand.
