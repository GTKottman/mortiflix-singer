# The singer service's HTTP API

Everything the editor, Booth, Training and Tune pages, the DAW plugin, the MCP server and the CLI do goes through
this API. Paths are given without the prefix: through Mortiflix Music they are under `/api/singer`, the desktop app
serves them at `singer://localhost/api/singer` (Windows: `http://singer.localhost/api/singer`), and the service
itself answers on its socket (`~/MortiflixSinger/singer.sock`), on `--stdio` frames, or on `--port`.

POST requests through Mortiflix Music need the header `x-mortiflix: 1`. JSON in, JSON out unless noted.
`?name=` is the singer (Booth/Training voice name, default `you`).

## Projects and rendering

| Method | Path | Body / result |
| --- | --- | --- |
| GET | `/projects` | `[{name, modified}]`, newest first |
| GET / POST | `/projects/<name>` | a `.msing` project (JSON); POST saves it |
| POST | `/render` | `{project, quality: "preview"\|"final", track?, name?}` → `{tracks: {id: [phrase]}}`; a phrase has `hash, url, start_ms, end_ms, pitch [[ms, midi]], phones [[ph, start, end]], phone_words, note_ids, first_tick, take, tone`. With `name` and final quality it also writes the plugin's mix file |
| GET | `/render/<hash>.wav` | a rendered phrase |
| POST | `/check` | `{project, track?, diction?}` → per track `{tuning: [{note, cents}], words: [{word, notes, ok, score, heard}], summary}` |
| POST | `/export` | `{project, format: wav\|mid\|musicxml\|msing, track?, bits?: 16\|24\|32, sample_rate?: 44100\|48000, include_backing?}` → the file |
| POST | `/import?filename=` | raw MIDI / MusicXML / UST / SVP / VSQX / VPR / msing → a project |
| POST | `/phonemize` | `{voice, lang?, words: [...]}` → `{phonemes: {word: [ph]}}` |
| GET / POST | `/autosave` | newest unsaved editor state / `{name, project}` to keep a copy |
| GET | `/mix/<name>` | what the DAW plugin plays: tracks with gain/pan/mute/solo and phrases with download urls |

## Voices and media

| Method | Path | Body / result |
| --- | --- | --- |
| GET | `/voices` | `{voices: [{name, range, license, commercial, image}], modes, langs}` |
| GET | `/voices/<name>/icon.png` | the voice's picture |
| GET | `/downloads` · POST `/downloads/start?id=` | official voice/vocoder downloads and their progress |
| POST | `/backing?filename=` | raw audio → `{file, name, duration}` (a project's backing track) |
| GET | `/backing/<sha1>.<ext>` | that audio |
| GET | `/scripts` · `/scripts/<bundled\|yours>/<file>.js` | editor scripts |
| GET | `/inbox` · `/inbox/<file>.mid` | MIDI captured by the DAW plugin (the second returns it as a project) |

## Booth and training

| Method | Path | Body / result |
| --- | --- | --- |
| GET | `/script?name=` | the Booth lines (fixed script + set D from your songs) |
| POST | `/booth/songs?name=` | `{name: project}` or `{project}` → lines from that song added as set D |
| POST | `/booth/take?name=&id=&preroll=` | raw WAV of a take → its grade report (`grade`, `problems`, `key_offset`, ...) |
| GET | `/booth/take.wav?name=&id=&take=` | a recorded take |
| POST | `/booth/keep?name=&id=&take=` | keep that take for training |
| GET | `/booth/progress?name=` | kept lines per set, the next line, every take's grade |
| GET | `/train/status?name=` | recorded minutes, kit/environment, GPU, running job, stages done, log tail |
| POST | `/train/start?name=` | `{steps?, smoke?, vocoder?}` starts training (dataset → models → voice, optionally its own vocoder) |
| POST | `/train/stop` · `/train/kit` | stop the job · install the training kit |

## Tune and the bridge

| Method | Path | Body / result |
| --- | --- | --- |
| POST | `/tune/upload?filename=` | a vocal (→ `{file, duration}`) or a `.mid` (→ `{file, notes}`) |
| POST | `/tune` | `{wav, notes? \| key?: {root, scale}, amount, speed, vibrato, offset_ms}` → before/after curves, per-note cents, `url` of the tuned WAV |
| GET | `/tune/file/<file>.wav` | the original or tuned vocal |
| GET / POST | `/bridge` | status / `{project, transpose}` starts a conversion into your voice |
| GET | `/bridge/<key>.wav` | the converted vocal |
