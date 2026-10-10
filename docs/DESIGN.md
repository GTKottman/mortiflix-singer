# Mortiflix Singer — Design Document

Oct 10, 2026 · @Gerrod Noordsy

## 1. Goal and the bar to beat

Mortiflix Singer turns a MIDI part plus lyrics into a finished lead vocal in your own voice, at a quality a listener takes for a human singer, inside your FL Studio workflow, and every file it makes is yours.

The bar is set by two commercial products. Synthesizer V Studio 2 Pro (Dreamtonics, $99 one-time with one voice, [source](https://dreamtonics.com/download-free-trials/)) and ACE Studio 2 (about $398, yearly billing). Both are trained on hours of professional singers and let you edit notes, words, timing, pitch and tone.

| What they do | Synthesizer V 2 Pro | ACE Studio 2 | Mortiflix Singer must |
| --- | --- | --- | --- |
| Sing MIDI + lyrics | Yes | Yes | Yes, from FL, a .mid, Mortiflix Music or the app |
| Natural pitch (scoops, vibrato) | AI pitch + manual curves | AI pitch | AI pitch model + editable curve + presets |
| Phoneme timing control | Dedicated panel | Limited | Per-phoneme drag in the piano roll |
| Retakes (new variation of a phrase) | Pitch, timbre, timing | Yes | Pitch and timing retakes with a seed per phrase |
| Your own voice | No (their voices only) | Voice cloning, paid | Your trained model, owned by you |
| Runs on | Windows, macOS | Windows, macOS | Linux PC (render) + Windows Lappy (FL plugin) |
| Output ownership | Commercial use with paid voice | Per their terms | Yours outright (your voice, your model) |
| Cost | $99+ | $398/yr | Free, open source parts |

**What "better" means here, concretely:**

1. **Your voice.** Neither product sings as you. This one is trained on your recordings.
2. **In tune by construction.** You can't hear pitch errors, so every render is measured and any note more than 20 cents off is flagged before you hear it.
3. **Words checked automatically.** A diction check flags any word a listener would mishear ("chrome size" instead of "chrome sunrise").
4. **Wired into your workflow.** Mortiflix Music writes the vocal line and lyrics; the singer renders it; FL Studio receives it on the right track at bar 1.
5. **No lock-in.** No subscription, no account, no internet needed to render.

**Success criteria (all must pass before calling it done):**

- [ ] A blind A/B of one chorus: you pick ours over Synthesizer V's stock male voice, or call them equal.
- [ ] Every word of a full song passes the diction check.
- [ ] Every note lands within 20 cents of the MIDI (median), none past 50.
- [ ] A 3-minute song renders in under 2 minutes on the RTX 3080.
- [ ] From FL Studio: export MIDI + lyrics, get the vocal back on a mixer track, in under 5 clicks.

## 1b. Definition of done: Synthesizer V parity, minus their voices

The project is complete when every feature below works on Windows, macOS and Linux, from an installer anyone can download from the public GitHub repo, with voices trained by the user instead of bought. Each line is one acceptance test.

**Editing**

- [ ] Piano roll with words on notes, multiple tracks, tempo and time-signature changes, loops, markers
- [ ] Lyric entry: type a line onto notes, per-note edit, paste a sheet; syllable fit shown
- [ ] Phoneme editing per note; a phoneme timing panel with draggable boundaries
- [ ] Note groups (reusable phrases placed several times, edited once)
- [ ] Import MIDI (with lyric events), MusicXML, UST (UTAU), Synthesizer V `.svp`, Vocaloid `.vsqx` / `.vpr`; export MIDI and MusicXML
- [ ] Unlimited undo and redo, autosave, project recovery

**Voice control**

- [ ] AI pitch with an expressiveness amount; manual pitch drawing; vibrato, transition, scoop and overshoot per note; snap to scale
- [ ] AI retakes of pitch, timing and tone per phrase, with seeds and A/B between takes
- [ ] Parameter lanes: tension, breathiness, voicing, energy, gender, tone shift, velocity, mouth opening (if the trained model supports it)
- [ ] Vocal modes (presets), user-defined
- [ ] Duration and strength sliders per note
- [ ] Cross-lingual: English first; Latin and other languages by rule files
- [ ] Breaths (auto and manual)

**Sound and output**

- [ ] Real-time playback while editing, background rendering, preview vs final quality
- [ ] Export WAV per track or mixed, 44.1/48 kHz, 16/24/32-bit, from bar 1
- [ ] Plugin: VST3 and CLAP on all three systems, AU on macOS, synced to the host's transport, state saved in the host project
- [ ] Standalone app on all three systems

**Automation**

- [ ] Scripting API (JavaScript) for batch edits, like Synthesizer V's scripts
- [ ] Command line and HTTP API (section 17); MCP tools for Claude sessions

**Beyond Synthesizer V (your additions)**

- [ ] Train your own voice: Booth with live tuner, tone-deaf-first capture, one-button training (section 8b)
- [ ] Diction, tuning and timing checks on every render
- [ ] Pitch corrector for any vocal WAV
- [ ] Mortiflix Music integration (written parts and lyrics sung automatically)

## 2. System overview

A vocal is made in eight steps, from your notes and words to a checked WAV, and every model in the chain comes from one swappable voice package, which is how your own trained voice replaces the bridge voice with no other change.

&#91;embedded content: render pipeline · 8 steps\]

Pitch is highlighted because it is where this design differs most from tonight's attempts: the pitch is predicted the way a singer moves, then centred on each written note, so it sounds human and stays in tune. The same chain runs in the desktop app, the plugin, the command line and Mortiflix Music (section 18b).

## 3. Words to sounds (the phonemizer)

Every lyric is turned into a sequence of English phonemes from a fixed set of 41 plus two silences, and every phoneme is tied to the note it belongs to before anything is sung.

**The phoneme set** is ARPAbet without stress marks, the same 41 symbols the open voice SPORE was trained on: vowels `aa ae ah ao aw ax ay eh er ey ih iy ow oy uh uw`, consonants `b ch d dh dx f g hh jh k l m n ng p r s sh t th v w y z zh`, plus `SP` (silence) and `AP` (a breath). Your own voice model uses the same set, so the two are interchangeable.

**How a word becomes phonemes, in order of trust:**

1. **Your pronunciation dictionary** (`dict/user.yaml`): anything you've corrected. Always wins.
2. **The song's own spellings**: a lyric written `live{l ay v}` uses those phonemes for that one note.
3. **CMUdict** (134,000 English words, public domain).
4. **A letter-to-sound model** for words not in any dictionary (names, Latin, made-up words). The g2p\_en model is already installed. Its guess is shown in yellow in the app so you can correct it once and save it to your dictionary.

**Latin and other languages.** Latin chants ("fiat lux") go through a small Latin rule set (Church Latin: `c` before e/i = `ch`, `ae` = `ey`, every vowel pronounced) that outputs the same ARPAbet symbols. A new language = a rule file + a dictionary, no retraining, as long as its sounds exist in the English set.

**Splitting a word across notes.** A word's phonemes are split into syllables at its vowels: each vowel starts a syllable, consonants between two vowels split the way English does ("sun-rise" = `s ah n` | `r ay z`). In the lyric line you write `sun- rise`, or just `sunrise` over two notes and the app splits it for you.

| You write | Notes | Phonemes per note |
| --- | --- | --- |
| `keep` | 1 | `k iy p` |
| `sun- rise` | 2 | `s ah n` · `r ay z` |
| `sunrise` | 2 | same, split automatically |
| `wake _` | 2 | `w ey k` · (hold `ey`) |
| `+` | 1 | slur: carries the previous vowel to a new pitch |
| `br` | 1 | a breath (`AP`) |

**One syllable per note is enforced.** If a phrase has more syllables than notes, the app shows the extra syllables in red and offers: merge into a melisma, add notes, or change the words. This is the bug behind "chrome size now" and it can no longer happen silently.

## 4. Timing engine: how long each sound is held

A trained duration model decides how long every phoneme lasts, then the engine fits those lengths exactly into the notes so the vowel always lands on the beat.

**Time grid.** Everything is counted in frames of 512 samples at 44.1 kHz = 11.6 ms. A quarter note at 118 BPM is 0.508 s = 44 frames.

**Step by step, per phrase:**

1. **Encode.** The linguistic model reads the phonemes, which phonemes belong to which word, and each word's length in frames.
2. **Predict.** The duration model predicts a natural length for every phoneme from that context and the note's pitch (`dur.onnx`: in = encoder output + note per phoneme, out = frames per phoneme).
3. **Fit to the notes.** For each note: the vowel and everything after it belong to that note; the consonants before the vowel belong to the note before it (they are sung on the previous note's time). The predicted lengths inside each note are scaled so they add up to the note exactly. Consonants are scaled first only if they don't fit; the vowel absorbs the rest.
4. **Lead-in.** Result: an onset consonant starts before the beat by its own length (an "s" about 90 ms, a "k" about 60 ms, model-predicted), and the vowel begins on the beat. This is what makes it sound sung and not typed.

**Holding long notes.** A held note is just more frames of the steady vowel. The acoustic model generates each frame fresh (no loop, no stretched recording), so a 4-second hold is as clean as a short one. A closing consonant ("wake" → `k`) is placed at the end of the note, at its own predicted length.

**Rests and breaths.** A rest under 120 ms is absorbed into the previous note (legato). A rest of a beat or more gets an `AP` breath at its end, 150 to 300 ms long, unless you remove it.

**What you can edit (app):**

| Control | Where | Effect |
| --- | --- | --- |
| Phoneme handles | Drag the boundaries drawn under each note | Moves where one sound ends and the next starts |
| Consonant offset | Per note, in ms | Earlier or later attack ("lazy" vs "punchy") |
| Velocity (VELC) | Lane, per frame | Speaks the consonants faster or slower, x0.5 to x2 |
| Timing retake | Right-click a phrase | New duration prediction with another seed |
| Lock | Per note | Keeps your edits through any retake |

**Check.** After every render the timing check measures, per note, where the vowel energy starts versus the beat. More than 40 ms late on a downbeat is flagged.

## 5. Pitch engine

A trained pitch model draws the human pitch curve from the notes (slides, overshoot, vibrato, phrase-end falls), and a correction layer then guarantees the curve is centred on each written note, so it sounds human but is in tune by construction.

**Layer 1: the predicted curve.** `pitch.onnx` takes the phonemes, their frame lengths and the notes (pitch, length, rest or not) and outputs a pitch value per frame in semitones. It is a diffusion model: it starts from noise and refines it in 10 to 20 steps, so each seed gives a slightly different, equally natural take. An `expr` (expressiveness) value from 0 to 1 scales how far it strays from the flat notes: 0 = flat robot, 1 = the training singer's full style.

**Layer 2: correction to the notes.** For every note, the middle 60% of the curve is measured. Its median is moved onto the written note, keeping the shape (vibrato, scoop) around it. Result: the expressive shape stays, the centre is exact. The amount is a knob: 100% (default, for you) to 0% (raw model).

**Layer 3: your edits.** Drawn on top as an offset curve in cents, never lost on a retake.

**Built-in pitch tools in the app:**

| Tool | What it does |
| --- | --- |
| Pencil | Draw a pitch offset freehand over any notes |
| Vibrato box | Per note: start (ms), depth (cents), rate (Hz), fade-in. Default: start 250 ms, 25 cents, 5.5 Hz |
| Transition | Per note boundary: slide length 30 to 200 ms and shape (fast, smooth, late) |
| Overshoot / scoop | Per note: cents above or below the target at the attack |
| Flatten | Select notes, remove all expression (for robot effects, Daft Punk style) |
| Pitch retake | Right-click a phrase: a new curve from a new seed; your edits kept |
| Snap to scale | Corrects drawn edits to the song's key |

**The tuning check.** Every render is measured note by note (the median pitch of the middle half of each note against the written note). The report lists median error, the worst notes and any note more than 50 cents off. Target: median under 20 cents, none past 50. This exists because you can't hear when a note is off, so you never have to.

**Range.** Each voice declares its comfortable range (yours: roughly D2 to C3 from your recordings; SPORE: F#3 to G4). Notes outside it are shown in orange in the piano roll; the app offers to move the part by octaves, never by other intervals, so the song stays in key.

## 6. Expression: breath, tension, energy, tone

A variance model predicts four expression curves per frame from the words and the pitch, and you can push each one up or down with a lane in the app; the acoustic model sings with whatever the curves say.

| Curve | Predicted by | Range | What you hear | Lane name |
| --- | --- | --- | --- | --- |
| Energy | `variance.onnx` | -96 to 0 dB | How hard the note is pushed | ENE |
| Breathiness | `variance.onnx` | -96 to 0 dB | Air in the tone (soft, intimate) | BREC |
| Voicing | `variance.onnx` | -96 to 0 dB | Voiced vs whispered | VOIC |
| Tension | `variance.onnx` | -10 to 10 | Relaxed vs strained, belted | TENC |
| Gender (formant) | your lane only | -100 to 100 | Throat size: darker or lighter, same pitch | GENC |
| Velocity | your lane only | 0 to 200 | Consonant speed (see timing) | VELC |

Your lane is added to the prediction, never replaces it, so a retake keeps your intent.

**Vocal modes (presets).** A mode is a saved set of lane offsets applied to a whole track or a selection:

- **Soft**: breathiness +6 dB, energy -4 dB, tension -3.
- **Chest**: energy +3 dB, tension +2, breathiness -6 dB.
- **Belt**: energy +6 dB, tension +5, gender -15.
- **Whisper**: voicing -40 dB, breathiness +12 dB.
- **Robot**: expressiveness 0, vibrato off, breathiness -20 dB (for the Daft Punk-style parts).

Trip hop defaults to Soft, house to Chest. Your own modes save into the voice package.

**Dynamics across the song.** MIDI velocity sets each note's energy offset (velocity 64 = 0 dB, 127 = +6 dB, 1 = -12 dB), so a vocal line written in Mortiflix Music already carries its dynamics.

## 7. Acoustic model and vocoder

The voice is made in two stages: an acoustic model draws a 128-band mel spectrogram frame by frame from phonemes, durations, pitch and expression, and a neural vocoder turns that picture into 44.1 kHz audio.

**Acoustic model (DiffSinger).** A shallow-diffusion model: a fast first guess of the spectrogram, then a diffusion refiner that adds the detail (breath noise, rasp, formants) a real voice has. Inputs per phrase: phoneme tokens, phoneme frame lengths, pitch (Hz per frame), energy, breathiness, voicing, tension, gender, velocity, plus two quality knobs:

- **Depth** (0 to 0.6): how much of the diffusion is run. Higher = more natural detail, slower.
- **Steps** (4 to 100): refinement steps. 20 is the default; 50 for the final render.

**Vocoder (NSF-HiFiGAN).** Takes the mel spectrogram and the pitch curve and outputs the waveform. Because it is told the pitch directly (that's the NSF, "neural source filter"), the output pitch follows the curve exactly, which is what makes layer 2 of the pitch engine reliable. Settings: 44.1 kHz, hop 512, 128 mel bins, 40 Hz to 16 kHz.

**Audio spec of every render:** 44.1 kHz, 24-bit WAV, mono, peak at -3 dBFS, starting at song time 0 so it lines up at bar 1 in FL. Phrases are rendered separately, with 0.5 s of padding on both sides, and crossfaded in over 10 ms, so a change to one phrase re-renders only that phrase.

**Speed (measured target on the RTX 3080, 20 steps):** one 8-second phrase in under 2 s; a 3-minute vocal in under 90 s; preview quality (8 steps) at 3x faster. CPU only works too, at about 5x slower.

**One voice package, three modes.** A voice package holds its own acoustic, duration, pitch and variance models and names the vocoder it needs. The app loads any package that follows this layout (section 17), so SPORE, your trained voice and future voices work the same way.

## 8. Your voice: everything you will sing

You record about 75 minutes of singing over four sessions of 25 minutes; after trimming, about 55 minutes go into training, enough for a natural voice in your range (DiffSinger voices are commonly trained on 30 to 120 minutes).

**You never read a list cold.** The Recording Booth in the app (built on the own-voice booth already in mortiflix-oss) shows one line at a time, plays its guide melody in your headphones in your key, counts you in, records, and checks the take on the spot: level, noise, clipping, and whether you sang the words. A bad take is redone right there.

| Set | What you sing | Lines | Minutes |
| --- | --- | --- | --- |
| A. Held vowels | 8 vowels (ah, ee, oo, eh, oh, a as in cat, uh, eye) on every semitone from C2 to E3, 3 s each | 136 | 7 |
| B. Scales | "la", "na", "ma", "da" up and down a major scale at 70 and 110 BPM | 16 | 5 |
| C. Balanced lines | Short lines (6 to 10 syllables) chosen so every pair of sounds in English appears at least 3 times, each to a one-bar guide melody | 300 | 35 |
| D. Your songs | Undertow and Chrome Sunrise lyrics on their real melodies | 60 | 10 |
| E. Styles | 20 lines from set C, each sung soft, chest, belted and whispered | 80 | 10 |
| F. Holds | 20 long notes of 4 to 6 s, half straight, half with vibrato | 20 | 3 |
| G. Breaths and fillers | In-breaths, "ooh", "ah", hums | 30 | 3 |
| **Total** |  | **642** | **73** |

The full line list for set C is generated, checked for sound coverage and saved as a tab of this document in milestone 2. Examples of what set C looks like:

- "The quiet river keeps the lantern low"
- "Judge the shadowless ships by the shore" (the tool swaps out banned words like "shadow" only in songs, not here: training wants every sound)
- "Fresh thyme grows near the azure gate"
- "Choose a measure, then pour the vision"

**Your setup (any decent USB mic works):**

- Mic 15 to 20 cm from your mouth, pop filter, same spot every session.
- The deadest room you have: a closet, or blankets behind and beside you. Echo is the main enemy.
- 48 kHz or 44.1 kHz, 24-bit, mono. Peaks around -12 dBFS, room noise below -60 dBFS (the booth measures both before you start).
- Closed headphones for the guide, so it doesn't leak into the mic.
- Same time of day, water, no dairy before. Stop when your voice tires: tired takes train a tired voice.

**Your tuning does not have to be right.** Set A and B are pitch-corrected before training (section 9), and the model learns your tone, not your accuracy. What matters is clear words and a steady tone.

## 8b. The capture plan: from your sit-down sessions to a finished model

You do one thing: sit down, follow the Booth line by line and sing each one as well as you can while a live tuner shows you where your pitch is; everything after the last line (cleanup, labeling, training, testing) runs on its own and ends with your voice appearing in the app.

### Tone-deaf first (the rule behind every screen)

The process is built for singers who can't hear whether they're in tune but can match a key: your ears are never the judge, your pitch accuracy never decides whether a take is usable, and you are never asked to fix a note by ear.

1. **Labels come from what you sang, not from the guide.** Each take's notes are taken from your own measured pitch, snapped to the nearest semitone. A line sung a whole tone flat is still a perfect training example of your voice singing those notes. The model learns your tone, words and phrasing; pitch is supplied by the MIDI when it sings for you.
2. **"Follow me" guide mode (the default).** You hear one reference note, then the guide waits for your first sung note and transposes the rest of the line to wherever you landed. You can't be "off key": the key follows you.
3. **Steadiness matters, accuracy doesn't.** The only pitch grade that can ask for a redo is a wobble check: a note that drifts more than a semitone up and down inside itself (the model would learn the wobble). Being sharp or flat overall never triggers a redo.
4. **See it, don't hear it.** The tuner trace and needle show up/down arrows and a colour, and say it in words ("a little low, slide up") instead of asking you to listen. A **drone** mode plays the key's root note continuously so matching a key is as easy as matching a hum.
5. **Pitch-match practice (optional, 2 minutes).** Before a session the Booth plays a note and you hum until the needle turns green; it tells you how many tries it took. It's a warm-up, never a gate.
6. **Correction does the rest.** Section 9A centres every note; a take more than 30 cents off after correction is relabeled to what you sang rather than dropped (rule 1).
7. **No hidden pitch requirement anywhere else.** Range check, vowel holds and scales all accept whatever notes you produce; the Booth plots your real range and the model is trained on exactly that.

The effect: someone who can't sing in tune but can hold a steady note in roughly the right key gets a voice model that sings perfectly in tune, because tuning comes from the MIDI at render time, not from the recordings.

### Before the first session (10 minutes, once)

1. **Room check.** The Booth records 10 s of silence and shows the noise floor. Target below -60 dBFS; if not, it tells you what it hears (fan hum, computer noise, echo) and to move or add blankets.
2. **Level check.** You sing "ah" loud and soft. The Booth sets your input so loud peaks sit near -10 dBFS and warns if it clips.
3. **Range check.** You slide from your lowest comfortable note to your highest. The Booth measures your range (expected around C2 to E3) and transposes every guide melody into it, so nothing asks you for notes you don't have.
4. **Headphone check.** It plays the guide while you stay silent and confirms none of it leaks into the mic.

### The Booth screen during a take

| Area | Shows |
| --- | --- |
| Line | The words, large, the current syllable lit as you reach it |
| Guide roll | The target notes as bars scrolling right to left, a playhead in the middle |
| **Live tuner trace** | Your pitch drawn as a line over the target bars as you sing, green within 20 cents of the note, yellow within 50, red beyond |
| **Tuner needle** | A large needle for the note you're on: the note name, how many cents sharp or flat, steadied over 100 ms so it doesn't jitter |
| Level meter | Your input level with the -10 dBFS target marked |
| Progress | Set, line number, minutes done today, sets left |

**How a take goes:** press Space (or a foot pedal), hear one bar of count-in plus the guide melody, sing, release. The guide keeps playing softly in your headphones while you sing, and you can turn it off once you know a line.

### Right after each take (under 2 seconds)

The take is checked and given a grade:

- **Pitch:** how steady each note is (the wobble check). How close you were to the guide is shown for your interest only and never lowers the grade.
- **Words:** Whisper hears the take; a missing or wrong word is shown.
- **Level and noise:** clipping, too quiet, background noise.
- **Timing:** whether you started within a beat of the count-in.

**A** = keep and move on. **B** = keep (it'll be corrected). **C** = the Booth suggests one redo and says why ("the word 'river' was missing", "clipped on the last note", "the note on 'low' wobbled"). You can always redo or keep anyway. Up to three takes of a line are kept; the best one is used.

### The sit-down sessions

| Session | Sets | Lines | About |
| --- | --- | --- | --- |
| 1 | A held vowels, B scales | 152 | 25 min |
| 2 | C balanced lines 1 to 150 | 150 | 25 min |
| 3 | C balanced lines 151 to 300 | 150 | 25 min |
| 4 | D your songs, E styles, F holds, G breaths | 190 | 30 min |

Take a 2-minute break every 10 minutes; the Booth reminds you and drops a marker when your takes start getting worse (falling pitch grades = a tired voice). Any day, any order; it resumes where you left off.

### The finish line

When the last line of session 4 is kept, the Booth shows a summary: lines kept, average grade, total usable minutes, and any lines still at C. One button: **Build my voice**. From there it runs unattended:

1. **Clean** (minutes): trim, level, noise check (section 10).
2. **Correct** (minutes): pitch correction of every take to its guide (section 9A).
3. **Label** (about 30 minutes): phonemes aligned, notes fixed, flagged takes listed.
4. **Review** (optional, your choice): only the flagged takes, one screen each, keep or drop. Skipped = flagged takes are dropped.
5. **Train** (1 to 3 days on the 3080): acoustic and variance models, with validation renders every 10,000 steps that you can play from your phone.
6. **Test** (automatic): the new voice sings a test song; diction, tuning and timing checks run; a blind A/B against the bridge voice is prepared for you.
7. **Publish:** your voice (`you-v1`) appears in Voices and becomes the default for your songs. You get a notification.

### And then it keeps going

- Every song you finish with a recorded take can go back into the dataset (with your OK), so `you-v2` is trained on more of you.
- A gap report lists sounds or notes the model handles worst (from the checks), and the Booth makes a short top-up set of just those lines (10 to 15 minutes) for the next version.

## 9. Pitch correction

There are two correctors: one cleans your training recordings before the model learns from them, and one corrects any finished vocal (rendered or recorded) onto the song's notes, as gently or as hard as you choose.

**A. Training data corrector (automatic, before training).**

1. Track the pitch of every take with RMVPE (a pitch tracker built for singing, robust to breath and rasp).
2. Find each sung note from the guide melody the booth played, so the target is known, not guessed.
3. Move each note's centre onto its target with WORLD (a vocoder that changes pitch without changing tone), keeping your natural slides and vibrato around it.
4. Measure again: any note still more than 30 cents off is dropped from training rather than kept wrong.

Why it matters: the pitch model learns your style of moving between notes. Corrected data teaches it your style, in tune.

**B. Vocal corrector (a tool in the app, also usable on any WAV).**

| Setting | Values | Effect |
| --- | --- | --- |
| Target | MIDI notes, or key + scale | What "in tune" means |
| Amount | 0 to 100% | 100% = centre exactly on the note |
| Speed | 0 to 200 ms | 0 = hard snap (the T-Pain effect), 80 ms = natural |
| Keep vibrato | on/off | Corrects the centre, leaves the wobble |
| Formant keep | on | Changes pitch without the chipmunk effect (fixes the "SpongeBob" problem) |
| Range | per note or selection | Correct only what you select |

Before and after are shown as two pitch curves over the notes, with each note's error in cents, plus an A/B play button.

**On renders it rarely does anything**, because the pitch engine is already centred (section 5, layer 2). It's there for your own recorded takes, for imported vocals and for the conversion bridge (section 12).

## 10. Labeling: turning recordings into training data

Every recorded line ends up as a row that says exactly which sound starts and ends where and which note it's on; this is automatic because the booth already knows the words and the melody of every take.

1. **Cut.** Each take is trimmed to its line plus 0.3 s of silence on each side, resampled to 44.1 kHz mono, and loudness-matched to -20 LUFS.
2. **Words to phonemes.** The line's words go through the phonemizer (section 3), giving the expected phoneme string.
3. **Forced alignment.** The Montreal Forced Aligner (or SOFA, a singing-specific aligner) finds where each phoneme starts and ends in the audio. Output: a TextGrid per take.
4. **Notes.** Notes come from the guide melody, adjusted to where you actually sang them (using the aligned vowel starts). For free takes (set G) the note extractor SOME estimates them.
5. **Pitch.** The RMVPE pitch curve is stored per take (section 9A corrects it).
6. **Write the dataset.** One CSV row per take: name, phoneme sequence, phoneme lengths, note sequence, note lengths, slur flags. This is the exact format DiffSinger trains from.

**Automatic checks per take (a failing take is excluded and listed for a redo):**

- Alignment confidence: every phoneme found, none shorter than 20 ms or longer than 3 s (except held vowels).
- Words: Whisper hears the take; fewer than 80% of the letters matching the line = probably the wrong words.
- Level: peak below -1 dBFS, noise floor below -55 dBFS.
- Pitch: tracked on at least 70% of voiced frames.

**Review screen.** The app shows each take as a waveform with its phoneme boundaries and notes drawn on it. You can play any phoneme, drag a wrong boundary, or mark the take bad. You only look at the ones the checks flagged.

## 11. Training your voice

Two models are trained on your dataset with OpenVPI's DiffSinger (Apache-2.0) on the RTX 3080, then exported to the same ONNX files the app already runs, so your voice drops in where SPORE was.

| Model | Learns | Trains on | Estimated time on the 3080 |
| --- | --- | --- | --- |
| Acoustic | Your tone: words + pitch + expression → spectrogram | Every usable take | 1 to 2 days (about 160k steps) |
| Variance | Your timing, pitch style and breath: durations, pitch curve, energy, breathiness, voicing, tension | Every take with notes | About 1 day |
| Vocoder | Not trained: the shared NSF-HiFiGAN is used |  |  |

The times are estimates to be measured in milestone 4; the training runs in the background and the app shows progress, sample renders and the loss curve.

**Settings that matter (taken from the DiffSinger reference configs, adjusted for 10 GB of video memory):**

- Batch size by frames, not lines: about 50,000 frames per batch, halved if memory runs out.
- Mixed precision on, to fit in 10 GB.
- Pitch shifting augmentation of ±3 semitones (the model learns your voice a little outside your range) and the "gender" lane learned from it.
- Validation set: 10 held-back lines from set C plus 2 song excerpts, rendered every 10,000 steps so you can hear the voice improve.

**Starting from a base model.** If a pretrained English DiffSinger base model with an open license is available, training starts from it and needs less of your data; otherwise it starts from scratch. Which one is an open question (section 22).

**Versions.** Every training run is a numbered voice version (`you-v1`, `you-v2`...) with its dataset, config and sample renders kept, so a newer version that sounds worse can be rolled back.

**RAM and safety.** Training uses the GPU and up to about 8 GB of system RAM; the renderer is paused during training rather than sharing the GPU (the 3080 has 10 GB).

## 12. The bridge: singing in your voice before your model exists

Until your own model is trained, an open DiffSinger voice sings the part with real human timing and pitch, and a voice converter swaps its tone for yours, keeping the performance.

1. **Sing.** SPORE (an open English DiffSinger voice, CC BY-NC-ND: free for non-commercial work, [source](https://github.com/knoxstation/SPORE)) sings the MIDI and lyrics through the full engine. Its comfortable range is F#3 to G4, so a part written for you (D2 to C3) is sung an octave up.
2. **Convert.** SoulX-Singer's voice converter (Apache-2.0, already installed and the one you said "sounded good") turns it into your timbre, using your "Better Off" recording as the reference.
3. **Back down.** The conversion is fed the pitch curve from the engine minus 12 semitones, with the formants kept, so it lands in your range without the "SpongeBob" effect.
4. **Check.** Diction and tuning checks run on the result like any render.

**Why this beats what you heard tonight:** tonight's versions started from spoken words, stretched and flattened, so there was no human performance to convert. Here the source is a trained singer model with natural phrasing; the converter only changes who it sounds like.

**Limits, stated plainly:**

- SPORE's license forbids commercial use and modified redistribution, so bridge renders are for demos and writing, not for releases. Your trained voice (section 11) has no such limit.
- A converted voice is never as close to you as your own trained model; it is a bridge, kept as an option afterwards for voices you don't have.

## 13. Quality checks (run on every render)

Five automatic checks run after every render and their results appear on the phrases they concern, so problems are caught by measurement before you listen, and your ears judge only what passed.

| Check | How it measures | Pass | Shown as |
| --- | --- | --- | --- |
| Diction | Whisper hears each phrase alone (no lyrics, no song around it); every expected word must be found letter by letter | Every word ≥ 65% of its letters | The unclear word in red, with what was heard |
| Tuning | Median pitch of the middle half of each note vs the written note | Median < 20 cents, none > 50 | Off notes outlined orange, cents shown |
| Timing | Where each vowel's energy starts vs its note's start | Within 40 ms on downbeats | A marker where the vowel really starts |
| Artifacts | Spectral flux spikes, clicks, silence inside a note, energy dropouts | None | A warning icon on the frame |
| Range | Notes vs the voice's comfortable range | All inside | Orange notes |

**Why phrase-alone Whisper:** tonight, Whisper on the whole hook "heard" "Chrome Sunrise now" when the voice sang "chrome size", because it guessed from context. Heard one phrase at a time with no lyrics given, it caught that and every slip you heard ("lame's" for "limbs", "round" for "drowned"). This check is built and was validated against your ears.

**Fixes the app offers for a failed word,** in order: re-render the phrase with a new seed; lengthen the note; respell it (`live{l ay v}`); suggest a different word with the same syllable count.

**Listening tests.** For milestone sign-off, the app builds blind A/B pairs (ours vs a reference: Synthesizer V's trial voice, or the previous version) with random order, and records your pick. A version ships when you pick it or call it equal at least 7 times in 10.

## 14. The app: layout and every screen

The app is one editor screen modelled on how vocal synths are used (a piano roll where every note shows its word), plus four supporting screens: Voices, Booth, Training and Checks. It ships as a standalone desktop app for Windows, macOS and Linux (section 18b); the same interface also runs as a page inside Mortiflix Music on your PC (port 4747, no new port), reachable from Lappy or your phone over Tailscale.

### 14.1 The editor (main screen)

&#91;embedded content: editor layout · wireframe\]

Five areas, top to bottom:

1. **Top bar.** Song name, tempo, key, time signature, transport (play, stop, loop, follow), render quality (preview / final), the voice picker, and Export.
2. **Track list (left, 200 px).** One row per vocal track (lead, double, harmony): voice, mode (Soft / Chest / Belt / Whisper / Robot), mute, solo, volume, pan. A track can use a different voice.
3. **Piano roll (centre).** Bars across, pitch up the side with a keyboard. Each note is a bar with its **word written inside it** and its phonemes in small type underneath. The rendered pitch curve is drawn over the notes as a line; the written note is the bar. Rendered phrases are tinted; phrases waiting to render are hatched.
4. **Parameter lanes (under the roll, collapsible).** Pitch offset, vibrato, energy, breathiness, voicing, tension, gender, velocity. Draw with the pencil, smooth with the brush, reset with right-click.
5. **Inspector (right, 280 px).** For the selected note: word, phonemes (editable), length, velocity, vibrato box, transition shape, consonant offset, lock. For a phrase: retake buttons (pitch, timing, both), the seed, and its check results.

**Entering lyrics, three ways:** type a whole line into the lyric bar and it flows onto the selected notes one syllable each; double-click a note and type its word; or paste a lyric sheet and assign it by phrase. Syllables that don't fit turn red (section 3).

**Keyboard:** Space play, Enter render selection, L lyric bar, R retake, Q quantize, Ctrl+Z / Ctrl+Shift+Z undo / redo (unlimited, per project), Alt+drag duplicate, number keys 1 to 5 switch vocal mode.

**Play while editing:** rendered phrases play as audio; an edited phrase re-renders in the background within about 2 s, and the playhead plays the old render until the new one is ready (no waiting).

### 14.2 Voices

Cards for each installed voice: name, range (drawn on a keyboard), license (commercial / non-commercial in plain words), versions, a 10 s demo. Buttons: set default, import a voice package, delete.

### 14.3 Booth (recording your voice)

The set list from section 8 with progress per set. One line at a time: the words large, the guide melody drawn as notes, a count-in, record, instant check (level, noise, words, pitch), keep / redo. Sessions resume where you stopped.

### 14.4 Training

Dataset status (takes kept / flagged), the review list of flagged takes (section 10), a Train button, live progress (step, loss curve), and validation renders you can play every 10,000 steps. Finished versions appear in Voices.

### 14.5 Checks

The whole song's check report: every flagged word, off note and artifact, each a link that jumps to it in the editor.

**Look:** follows the Mortiflix design standard (docs/DESIGN-STANDARD.md): edges not boxes, one accent colour, no nested boxes, dark and light themes, works at phone width for the Booth and playback.

## 15. FL Studio integration

In FL Studio the singer is a VST3 instrument on its own channel: it shows the singer's editor inside the plugin window, renders on the same computer when it has a capable GPU (or on another machine, like your Linux PC, over the network), and plays the vocal back locked to FL's song position, so it behaves like Synthesizer V's plugin.

**Why the editor lives inside the plugin.** A VST instrument only receives notes while FL plays them, never the whole part in advance, and a singer needs the whole phrase (and its words) to render it. Synthesizer V solves this the same way: the notes and words live in the plugin's own piano roll. You get them in by dragging a MIDI clip from FL (or Mortiflix Music) onto the plugin window, or by typing them there.

**The plugin, "Mortiflix Singer" (Windows VST3, built in Rust with nih-plug like your Strata plugin):**

| Part | Does |
| --- | --- |
| Editor window | The app's editor page (section 14) shown in an embedded web view (WebView2), connected to the render server |
| Transport sync | Reads FL's tempo, time signature and song position every audio block |
| Player | Streams the rendered WAV for the current position, sample-accurate, with a 50 ms pre-roll cache |
| Drop zone | Accepts a .mid dragged from FL's piano roll or browser; lyrics from its lyric events or the lyric bar |
| Offline fallback | Keeps the last render in the FL project folder, so the song plays even if the PC is off |
| State | The project (notes, words, edits) is saved inside the .flp with the plugin state, plus a copy on the server |

**Where rendering happens.** Locally by default, with the same engine as the desktop app. For your setup, Lappy has no capable GPU, so its plugin is pointed at the Linux PC (RTX 3080), reached at `http://<render-pc>:4747` over Tailscale, as a thin client. Each edit sends only the changed phrases; the server returns their WAVs.

**Getting it to the mix:**

1. The plugin's output goes to its own mixer insert, where your vocal chain (EQ, compression, Strata Cylinder Role: Lead) applies like any instrument.
2. "Bounce to audio" in the plugin writes `Vocal - <song>.wav` into the FL project folder at bar 1 for printing and editing.
3. FL's normal export includes the vocal because the plugin plays during render (it reports its render to FL as realtime-safe since it only plays cached audio).

**Without the plugin (works from day one):** Mortiflix Music's song step exports the vocal WAV from bar 1; the existing Lappy watcher drops it into the project folder; it goes on the vocal track's audio clip (the same swap done tonight for Chrome Sunrise).

**Setup on Lappy:** one installer puts the VST3 in `C:\Program Files\Common Files\VST3`, then FL's plugin manager scans it. The plugin asks once for the server address (your render machine's name is filled in).

## 16. Mortiflix Music integration

Mortiflix Music already writes singable vocal parts and lyrics (built tonight: the vocals option, the lyrics step with the one-syllable-per-note check, the sing step and the vocal mix in the master); Mortiflix Singer becomes the singer that step calls.

**What already exists in Mortiflix Music (uncommitted, 119 tests passing):**

- New-song form: Vocals (Instrumental / Sung vocals), The voice, Lyrics.
- Blueprint check: one vocal role with a voice range; score check: notes a person can sing (range, nothing shorter than an eighth, a breath every 4 bars).
- Lyrics step (you approve the words): one line per vocal note, syllable counting, your never-use and 5% word rules, lyrics written into the vocal's MIDI.
- Sing step: calls the configured singer with `--midi --tags --out --beats-per-bar --transpose 0 --voice`, then runs the diction check.
- Master: the sung vocal replaces the guide synth, cleaned and levelled 1 dB over the music.

**What changes:** the studio's singer setting points at Mortiflix Singer's command line (`singer render`, section 17) instead of tonight's stopgaps, and the vocal step gains the tuning and timing checks from section 13.

**MCP tools (so any Claude session can drive it):**

| Tool | Does |
| --- | --- |
| `singer_render` | MIDI + lyrics (or a project) → WAV, with check results |
| `singer_check` | Run diction, tuning, timing checks on any vocal WAV |
| `singer_voices` | List voices, ranges, licenses |
| `singer_retake` | New take of one phrase with a seed |
| `singer_correct` | Pitch-correct a WAV to a MIDI part |
| `singer_train_status` | Dataset and training progress |

## 17. Files, formats and APIs

Three files and two interfaces carry everything: a project file, a voice package, a dataset folder, a command line and an HTTP API, all plain text or standard formats so nothing is locked in.

**Project file (`.msing`, JSON).** Tempo map, time signature, tracks; per track: voice, mode, lanes; per note: start (ticks, 480 per beat), length, pitch, lyric, phonemes (if edited), vibrato, transition, consonant offset, lock; per phrase: seeds and the render cache key. Imports and exports MIDI with lyric events and MusicXML.

**Voice package (folder, same layout as OpenUtau's DiffSinger voices, so any of those load too):**

```
voices/<name>/
  character.yaml      name, range, license, author, image
  dsconfig.yaml       acoustic model settings (sample rate 44100, hop 512, 128 mel bins)
  dsmain/             acoustic.onnx, linguistic.onnx, phonemes.json
  dsdur/ dspitch/ dsvariance/   the timing, pitch and expression models
  dict/user.yaml      your pronunciation fixes
  modes.yaml          your vocal modes
```

**Dataset folder (`datasets/<name>/`).** `raw/` (every take as recorded), `wavs/` (cleaned), `textgrids/` (alignments), `transcriptions.csv` (the training table), `booth.json` (lines, grades, which take is kept).

**Command line (`singer`).**

| Command | Does |
| --- | --- |
| `singer render song.mid --lyrics "..." --voice you-v1 --out vocal.wav` | Render |
| `singer render song.msing --track lead --out vocal.wav` | Render a project track |
| `singer check vocal.wav --midi song.mid --lyrics ...` | Diction, tuning, timing report |
| `singer correct take.wav --midi song.mid --amount 100 --speed 80` | Pitch-correct a WAV |
| `singer voices` | List voices |
| `singer dataset build --name you` | Clean, correct, label |
| `singer train --name you` | Train and export a voice version |

The Mortiflix Music singer contract (`--midi --tags --out --beats-per-bar --transpose --voice`) is supported as an alias.

**HTTP API (inside Mortiflix Music on :4747, under `/api/singer/`).** `POST /render` (a phrase or a project, returns WAV + checks), `GET /voices`, `POST /booth/take` (upload a take, returns grades), `GET /train/status`, `WS /live` (render progress and the Booth's live pitch for the tuner). The FL plugin and the web app both use it.

## 18. Performance, hardware and storage

Everything renders and trains on your Linux PC (RTX 3080, 10 GB video memory; 31 GB RAM); Lappy only runs FL Studio and the thin plugin.

| Job | Where | Video memory | RAM | Target time |
| --- | --- | --- | --- | --- |
| Render, preview (8 steps) | PC GPU | about 2 GB | about 2 GB | 8 s phrase < 1 s |
| Render, final (20 to 50 steps) | PC GPU | about 3 GB | about 2 GB | 3-min song < 90 s |
| Booth live tuner | Browser, on whatever device you sing into | none | small | Pitch shown within 50 ms |
| Take grading | PC CPU | none | about 3 GB (Whisper) | < 2 s per take |
| Labeling | PC CPU | none | about 4 GB | about 30 min for the full dataset |
| Training | PC GPU | up to 9 GB | up to 8 GB | 1 to 3 days, unattended |

The render and training queues share the GPU one job at a time (the same rule as the Remotion render queue), so a training run pauses while you render a preview, then resumes.

**Storage:** voices about 300 MB each; your raw recordings about 1.5 GB (24-bit, 75 minutes, with retakes); training checkpoints about 2 GB per version (keep the last three); render cache about 50 MB per song.

## 18b. Platforms, install and the engine

One render engine written in Rust powers the desktop app, the plugin and the server alike, so a user installs one package and needs no Python, no command line and no account to sing.

| Piece | Built with | Windows | macOS | Linux |
| --- | --- | --- | --- | --- |
| Render engine | Rust + ONNX Runtime (the `ort` crate) | DirectML (any GPU), CUDA (NVIDIA), CPU | CoreML (Apple Silicon), CPU | CUDA, CPU |
| Desktop app | Tauri (Rust core + the web interface) | .msi installer | .dmg, signed and notarised | .AppImage, .deb, Flatpak |
| Plugin | Rust + nih-plug | VST3, CLAP | VST3, CLAP, AU | VST3, CLAP |
| Trainer | Python, DiffSinger, packaged by the app | NVIDIA GPU, one click | Apple Silicon (slower) | NVIDIA GPU, one click |
| Phonemizer, checks | Rust (dictionary + rules); Whisper via whisper.cpp | yes | yes | yes |

**Install for a user:** download from the GitHub Releases page, run the installer, open the app. First run: pick a voice (the bridge voice is offered as a download, with its non-commercial license shown), or start the Booth to make your own.

**Training on each system.** Training needs a GPU with at least 8 GB: NVIDIA on Windows and Linux; on Apple Silicon it runs through PyTorch's Metal backend at an estimated 3 to 5 times longer. The app installs the trainer's Python environment itself (a private Miniforge folder) on first use; users never see it.

**Release pipeline.** GitHub Actions builds and tests all three systems on every tag and uploads the installers to Releases; an update check in the app points to new releases.

**Repository.** `github.com/GTKottman/mortiflix-singer`, public, with docs, issues and this design as `docs/DESIGN.md`.

## 19. Licensing and ownership

Your voice model, your recordings and every vocal rendered with your model are yours with no strings; the only restricted part is the bridge voice, SPORE, which is non-commercial.

| Component | License | What it means for you |
| --- | --- | --- |
| DiffSinger (OpenVPI), training + models | Apache-2.0 | Use, change, sell |
| OpenUtau (reference for driving the models) | MIT | Use, change, sell |
| NSF-HiFiGAN vocoder (OpenVPI) | Check the release notice before shipping releases: open question | Rendering for your own songs is fine; redistribution terms to confirm |
| SPORE voice | CC BY-NC-ND 4.0 + custom terms | Demos only, no commercial songs, credit Knoxstation |
| SoulX-Singer (converter) | Apache-2.0 | Use, change, sell |
| CMUdict | Public domain | Anything |
| Whisper (checks) | MIT | Anything |
| Your recordings, dataset, model | Yours | Anything; never uploaded anywhere |
| Mortiflix Singer code | Same as mortiflix-music-oss (AGPL) unless you choose otherwise | Your call (section 22) |

## 20. Testing plan

Every part has fast automatic tests that run in seconds on fixtures, plus a small set of real-audio tests; nothing is called done until its test passes and, for anything you hear, until you've listened to it.

**Fast tests (seconds, run on every change):**

- Phonemizer: 200 words with known phonemes, Latin rules, syllable splitting, red-syllable detection.
- Timing fit: phoneme lengths always sum to each note; vowels start on note starts; consonant lead-in present.
- Pitch correction layer: a synthetic curve with known offsets lands within 2 cents of each note.
- Project file: round-trip MIDI with lyric events and `.msing` without loss.
- API: render endpoint with a tiny stand-in model (no GPU) returns a WAV of the right length.
- Booth grading: synthetic takes (clipped, noisy, wobbly, off-key but steady) get the expected grade; off-key but steady must pass (tone-deaf rule).

**Real-audio tests (minutes, run per milestone):**

| Test | Input | Pass |
| --- | --- | --- |
| Chrome Sunrise hook | 10 notes, "Ride the light..." | All checks pass; you approve by ear |
| Undertow chorus 1 | 32 notes, slow, deep | All checks pass; you approve |
| Fast passage | 16 eighth notes at 140 BPM | Diction passes |
| Long holds | 4 notes of 3 s | No artifacts; vibrato present |
| Latin chant | Chrome Sunrise v8 lines | Diction passes on respelled words |
| Full song | Undertow vocal, 192 notes | Renders < 2 min; every check passes |

**Listening sign-off.** Each milestone ends with you hearing a short A/B (section 13) and saying yes or no. A "no" with a reason goes back into the work, not into the next milestone.

## 21. Build order

Nine milestones, each ending with something you can hear or use and an automatic check; the order puts a real singing voice in your ears first, your own voice model next, and polish and distribution last.

1. **M0, engine proof (started tonight).** SPORE sings the Chrome Sunrise hook through our own code driving the DiffSinger models (Python, onnxruntime). *You hear:* a human-sounding sung hook. *Check:* diction and tuning pass.
2. **M1, render engine.** The engine in Rust: phonemizer (CMUdict + Latin rules), timing fit, pitch with correction layer, variance, acoustic, vocoder, phrase cache; `singer render` CLI; all fast tests from section 20. *You hear:* Undertow's full vocal by SPORE in under 2 minutes.
3. **M2, bridge + Booth.** Conversion into your voice (section 12); the Booth with live tuner, follow-me guide, drone, take grading, the generated 642-line script (added as a tab here). *You do:* session 1. *You hear:* the bridge version of Undertow.
4. **M3, editor v1 (web).** Piano roll with words on notes, lyric bar, render, playback while editing, export WAV, MIDI and MusicXML import/export. Runs inside Mortiflix Music. *You do:* edit and render a song yourself.
5. **M4, your voice.** Sessions 2 to 4, dataset build, review, training, `you-v1` published. *You hear:* yourself singing Undertow in tune. *Check:* blind A/B vs the bridge.
6. **M5, editor v2.** Parameter lanes, pitch tools, vibrato and transition boxes, retakes with seeds, vocal modes, phoneme timing panel, note groups, `.svp` / `.ust` / `.vsqx` imports, checks panel.
7. **M6, desktop app.** Tauri app with the Rust engine, installers for Windows, macOS and Linux, GitHub Actions release pipeline, public repo and first pre-release.
8. **M7, plugin.** VST3 + CLAP (+ AU on macOS) with the embedded editor, transport sync, cached playback, state in the host project; tested in FL Studio on Lappy and in REAPER on Linux.
9. **M8, v1.0.** Scripting API, MCP tools, Mortiflix Music's sing step on the new engine, every item in section 1b ticked, blind A/B against Synthesizer V passed, v1.0 released.

**Working rules for the build:** every milestone is committed and pushed to the public repo; fast tests run in seconds; nothing slow (training, full renders over a minute) starts without telling you first; every audio result is sent to you the moment it exists.

## 22. Risks, open questions and your decisions

The biggest risk is the quality of a voice trained on about an hour of recordings from a non-singer; it is handled by the tone-deaf-first capture, pitch correction, a base model if one exists, and a top-up loop for weak spots.

| Risk | Likelihood | What we do |
| --- | --- | --- |
| Your first voice model sounds thin or blurry | Medium | Top-up sessions on the weak sounds; more data; start from a base model |
| No open-licensed English base model to start from | Medium | Train from scratch (needs the full 55 usable minutes); look at community models with permissive licenses |
| Rust port of the inference takes longer than planned | Medium | M0 to M5 run on the Python engine; the Rust engine replaces it in M6 without changing the app |
| Plugin playback in FL glitches (timing, offline render) | Medium | Cached playback only; test plan in M7; bounce-to-audio as the safe path |
| macOS distribution blocked by Gatekeeper | High without signing | Needs an Apple Developer account (decision below) |
| Vocoder license limits redistribution | Unknown | Read OpenVPI's notice; if needed, train our own vocoder on open data (adds a week) |

**Decisions only you can make:**

- [ ] **License of Mortiflix Singer's code:** AGPL like mortiflix-music-oss (anyone who changes it must share), or MIT (anyone can use it in anything, including closed products).
- [ ] **Apple Developer account** ($99/year) to sign the Mac app; without it Mac users must right-click → Open past a warning.
- [ ] **Windows code-signing certificate** (about $200 to $400/year), or accept the "unknown publisher" warning for now.
- [ ] **The name.** Working name: Mortiflix Singer.
- [ ] **Whether your voice model is ever shared.** Default: never; it stays on your machines.
- [ ] **Recording mic.** Which mic you'll use for the Booth sessions.
