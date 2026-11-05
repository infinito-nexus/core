# Narrator voices

| File | Voice | Use |
|---|---|---|
| `narrator.wav` | **Bella**, the default narrator: a synthetic, friendly female tech voice made locally with Kokoro-82M's `af_bella` (2026-10-07), 16 s | every film unless the user picks another voice |

## Rules

- `narrator.wav` is synthetic, so no person's consent is involved. It was generated locally with Kokoro-82M (Apache-2.0), reading: "Oh, hi! I'm so glad you're here. Honestly, this is my favorite part, showing people around. Don't worry, nothing here is complicated. We'll go step by step, and if something looks a little weird, just ask me. Ready? Okay, let's have some fun with this." No third-party service terms apply, so films made with it can be published royalty-free. Chatterbox output still carries Resemble's inaudible Perth watermark.
- Bella's settings: `exaggeration 0.52`, `cfg_weight 0.5`, `temperature 0.75`. At `exaggeration` 0.6 and above her pitch swings 11+ semitones a line and she sounds sing-song and synthetic; at 0.4 she sounds flat.
- Only voices that are safe to share live in this folder. A real person's voice, or a voice generated on a service whose terms forbid feeding its output into another model, stays outside the skill (for example in `~/voices/`) and is pointed at per film.
- A voice kept outside the skill can carry its chosen settings in a JSON next to its sample (e.g. `~/voices/<name>.json` with `sample`, `exaggeration`, `cfg_weight`, `temperature`); read it and use those values for the narrator. More expressive settings (around `exaggeration 0.8`, `cfg_weight 0.3`) suit a sassy, slower delivery for some real voices; always test one line in 2-3 styles and let the user pick by ear.
- A user's own voice: a clean 10-20 s sample (quiet room, natural presenting pace, no music), trimmed to start after any consent sentence, used only with that person's consent for that use. Point the narrator's `sample` in `voiceover.json` at it.
