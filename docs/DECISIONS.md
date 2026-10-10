# Decisions log

Decisions made while building, with who made them. "Default" = picked by the builder (Claude) on the owner's
instruction to choose the recommended option and keep going; the owner can reverse any of them.

| Date | Decision | Made by | Why |
| --- | --- | --- | --- |
| 2026-10-10 | Code license: AGPL-3.0 | Default | Same as mortiflix-music-oss: anyone who changes and ships it must share their changes |
| 2026-10-10 | Name: Mortiflix Singer | Default | The working name in the design doc |
| 2026-10-10 | No code signing for now (Windows/macOS installers unsigned) | Default | Signing costs money; users click past one warning until it's bought |
| 2026-10-10 | The app runs inside Mortiflix Music on :4747 during development (no new port) | Owner | Asked directly |
| 2026-10-10 | The singer service talks over a UNIX socket (~/MortiflixSinger/singer.sock) | Default | Follows from "no new port" |
| 2026-10-10 | Bridge voice: SPORE (CC BY-NC-ND), non-commercial demos only | Default | The only open English DiffSinger voice found; the owner's own voice replaces it |
| 2026-10-10 | Retakes change the render's random draw (a take number in the cache key), not a model seed | Default | DiffSinger's ONNX models draw their own noise; there is no seed input |
