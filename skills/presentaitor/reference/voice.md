# Voice: what the first runs taught

Read before the first `tools/film.py` run.

## Setup

- Chatterbox must be installed once: `bash <SKILL>/engine/scripts/install.sh chatterbox` (about 4 GB). Kokoro is the light fallback, but its delivery is flat; use it only for timing drafts.
- In the sandbox the venv and `~/.cache` are read-only. `film.py` sets `NUMBA_CACHE_DIR` and `HF_HOME` under `/tmp/presentaitor-cache`; the first run downloads the weights (about 3 GB) there, and they vanish on reboot. To keep them: `cp -r /tmp/presentaitor-cache/hf/hub/* ~/.cache/huggingface/hub/` outside the sandbox, then run with `HF_HOME=~/.cache/huggingface`.

## Running

- One voice job at a time. Each Chatterbox process takes every core; eight in parallel ran about 100x slower than one.
- About 40 s per line (three takes, the most natural kept): a 9-chapter series of about 110 lines takes about 75 minutes. Takes are cached in `<film>/out/voiceover/<backend>/`, each with a `.key` of its text and voice settings; a rerun logs `cache hit` or `cache miss` per line and only speaks the misses.
- `film.py` runs `engine/scripts/voiceover.py`, which speaks, trims, lays out `timing.json` and mixes in one pass.

## Timing (voice first)

- The takes set the timing. Lines in a scene are 0.35 s apart, a scene change leaves 0.8 s, and each scene ends on a half beat of the music. `"hold": seconds` on a line adds room for action on screen after it; `"min": seconds` on a scene keeps it at least that long (end cards).
- `timing.json` (and `src/timing.js` for the page) holds every line's `start`, `end` and `slot` (until the next line starts), the scenes, and per-word times in `words` (also in `words.json`) for captions. Use `line("n03").start` and `scene("app").start` in scenes; `B(n)` still places moments on the music.
- Footage follows the voice: `"footage": {"src": ...}` in the script and `"clip": [from, to]` per line. A clip shorter than its slot holds its last frame (the freeze lasts the line plus the gap); a longer clip plays up to 1.5x faster, then is cut.
- Takes are trimmed at both ends, and a pause inside a take is cut to about 0.5 s (never more than 0.6 s). A fresh take must last 0.8-1.3x a plain reading (word count / `"wps"` of the voice, 3.0 by default); Chatterbox speaks it again with new seeds up to three times, then keeps the last take with a warning. Kokoro and `say` speak a line the same way every time, so reword a line they flag.
- Very short lines ("Next, filters.") often miss the range. Write closers of at least five or six words ("Next up: filters that run on the server.").
- The music bed should be at least as long as the film; the mix fades it out over the last 2 s and warns when it is too short.

## Narration

- A narrator voice is not the person on screen: write third person ("Alejandro signs in") unless the user wants first person.
- Spell what the model misreads: "infinito dot test", "fifteen point oh", "elliptic curve" instead of "Ed25519"; keep the exact names in the on-screen callouts.
- Say the viewer's domain ("mail dot your domain"), never the lab domain, when telling viewers what to type.

## Playback

The renders are H.264 with stereo AAC and play everywhere. A silent player on Linux is the player, not the file: `ffplay -autoexit <file>` proves it. mpv: put `ao=pulse,alsa` in `~/.config/mpv/mpv.conf`. GNOME Videos (Totem) needs `gstreamer1.0-libav`, or make mpv the default with `xdg-mime default mpv.desktop video/mp4`. Send films over Telegram as files, not videos, so they are not recompressed.
