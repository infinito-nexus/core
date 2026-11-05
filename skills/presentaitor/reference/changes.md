# Changing a finished film

Read when the user wants to change something in a film or series that is already built. Find the cheapest path: most changes need no re-render.

| Change | Edit | Then run | Re-render? |
|---|---|---|---|
| Narration text, add or drop a line | `<film>/voiceover.json` (`lines[].text`, the scene's `lines`) | `python3 <SKILL>/tools/film.py preview <film>`, then `render <series> --chapter NN --final`; only the changed take is spoken again | only the scenes from the first one whose timing moved |
| Narrator voice | `voices.narrator.sample` and its settings in `voiceover.json`; every take's key changes, so every line is spoken again | `film.py render <series> --chapter NN --final` | yes, the timing follows the new takes |
| Voice or music loudness | `mix.music_gain` (+-0.05), `duck_ratio` | `film.py render ...`: takes and every scene are reused, only the mix and the mux run | no |
| Music track or section | new track in `audio/source/`, `beats.py`, `music_edit.py`, at least as long as the film | `film.py render ...` | only if `"bpm"` changes (scene ends snap to half beats) |
| On-screen text, callouts, plates, presets | `<film>/src/scenes.js` | `film.py preview <film>`, then render | yes, that chapter (the page code is part of every scene's cache key) |
| Brand colours or fonts | `<film>/src/film.css`, re-pack `assets.js` | render | yes, every affected chapter |
| Footage | `"footage"` and the lines' `"clip"` in `voiceover.json` | render | the scenes whose clips changed |
| Output format | `Output:` in `SERIES.md` | `film.py join <series>` | no |

Chapters whose `voiceover.json` has no `"scenes"` are v1 films with fixed start times: `tools/voice_all.py <film> ...` still voices, re-times (`tools/reflow.py`), mixes and remuxes them without a re-render.

Voice runs go one chapter at a time (Chatterbox takes every core). Renders can run in parallel.

After any change, compress the final as the series did (`-crf 26 -r 30`), and keep the previous final as a backup until the user approves the new one.
