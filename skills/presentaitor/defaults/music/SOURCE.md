# Default track: "pulse"

- Files: `pulse.mp3` (96 s, instrumental), beat grid `grid-pulse.json`
- Origin: original, made with ACE-Step 1.5 (acestep-v15-turbo, acestep-5Hz-lm-1.7B), rendered locally on CPU, seed 42, 2026-10-14
- Licence: ACE-Step 1.5 code and weights are MIT; its model card allows commercial use of generated output. No third-party attribution required.
- Credit line (end card): "Music: original, made with ACE-Step 1.5"
- Tempo: 104.9 BPM (onset autocorrelation; ACE-Step requested 104, heard 103; `beats.py` locks onto 70, two thirds of it, so use `grid-pulse.json`, not a fresh `beats.py` grid). Beats at 0.565 s + n × 0.572 s. Four-on-the-floor, so the downbeat is a guess; bar 1 starts on the first beat. One breakdown before the groove returns and fades out.
- Mix: a bright lead fills the frame (fill 31%, crest 15 dB); keep `music_gain` lower than for Industrial Cinematic (start at 0.5).
- Notes: copyright protection for AI-generated music differs by country; some platforms (e.g. YouTube) ask for AI-generated audio to be labelled.

# Alternative: Industrial Cinematic

- Files: `industrial-cinematic.mp3`, `grid.json`
- Artist: Kevin MacLeod (incompetech.com), https://incompetech.com/music/royalty-free/mp3-royaltyfree/Industrial%20Cinematic.mp3
- Licence: Creative Commons Attribution 4.0 (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/
- Downloaded: 2026-10-06
- 110 BPM; drops at track bars 6, 16, 33, 48, 79; breakdowns at 37, 59, 101 (`grid.json` holds the exact grid)
- Credit line, required on an end card or in the description of every film that uses it:
  "Industrial Cinematic" Kevin MacLeod (incompetech.com), Licensed under Creative Commons: By Attribution 4.0 License, http://creativecommons.org/licenses/by/4.0/
