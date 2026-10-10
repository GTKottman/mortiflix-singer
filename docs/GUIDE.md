# Mortiflix Singer: a short guide

## 1. Hear something now

Open the **Editor** (Singer home → Editor, or your project under *Your projects*). Type a line in the lyrics bar and
press Enter: the words flow onto the selected notes. Press **Space** to play; it renders as you edit. **Check**
(Ctrl+K) listens to every word and measures every note; **Fix unclear words** tries new takes where a word came out
mushy. Press **?** for every key.

The starter voice is SPORE (non-commercial). For anything you release, use your own voice (below).

## 2. Make it your voice

1. **Booth** (Singer home → Booth). Allow the microphone, check the room, set your level, find your range.
   Record on the computer that runs Singer (`http://localhost:4747/singer/`) or in the desktop app: browsers only
   allow the microphone on secure pages, so the Tailscale address from another machine can't record.
2. Sing the lines. You don't need to be in tune: the tuner shows where you are, *Follow me* moves the key to you,
   and takes are graded only for being steady and clear. A and B takes are kept.
3. Four sittings of about 25 minutes (held vowels and scales, two halves of the balanced lines, then your songs,
   styles, holds and breaths). Breathe in audibly before you sing: the voice learns breaths from that.
   Add your own songs (*Add its lines*): they teach the voice the most. The Booth tells you when to rest.
4. When it says **Build my voice** (about 30 minutes kept, an hour is better), go to **Training** and press Start.
   It runs for hours on the graphics card; you can close the page. Tick *own fast vocoder* if you'll render on a
   laptop without a graphics card.
5. Your voice appears in the editor's voice list. Everything in it is yours to use commercially.

Until then, **Export → WAV in my voice** converts a render into your voice (the words get a little smudged).

## 3. In FL Studio (or any DAW)

1. Install the plugin (VST3) and add **Mortiflix Singer** as an instrument on its own channel and mixer insert.
2. On the laptop, set **Renders from** to `http://mothership.tail339f12.ts.net:4747`; on the PC leave it empty.
3. Pick the project. Set FL's tempo to the project's. Press play: the vocal plays in time.
4. Edit in the Singer editor (*Open in the editor*); the plugin picks up each new render within a second.
5. *Bounce to WAV* prints the vocal (Documents/Mortiflix Singer) for an audio track.
6. Want to write the melody in FL? Turn on *Capture MIDI*, play the part into the plugin, *Send to Singer*, then in
   the editor: Open → *From your DAW* → *Into this track* and type the words.

## 4. Tune any vocal

Singer home → **Tune**: drop a vocal and its MIDI part (or pick the key), press *Tune it*, compare before and after,
download. It never moves your octave, so no chipmunk sound. *Keep vibrato* keeps your wobble and only centres notes.

## 5. Where things are

- Projects, voices, recordings and renders: `~/MortiflixSinger` (on Windows `C:\Users\<you>\MortiflixSinger`).
- What's done and what isn't: [STATUS.md](STATUS.md). Choices made while you were away: [DECISIONS.md](DECISIONS.md).
