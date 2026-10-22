import json
import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

home = Path(os.environ.get("MOTION_DESIGNER_HOME", Path.home() / ".cache/motion-designer"))
models = Path(os.environ.get("MOTION_DESIGNER_KOKORO_MODELS", home / "kokoro/models"))
lines, cache = json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2])
cache.mkdir(parents=True, exist_ok=True)
kokoro = Kokoro(str(models / "kokoro-v1.0.onnx"), str(models / "voices-v1.0.bin"))
voices = set(kokoro.get_voices())

for line in lines:
    s = line.get("settings", {})
    voice = s.get("kokoro", "af_heart")
    if voice not in voices:
        raise SystemExit(f"{line['id']}: no Kokoro voice {voice!r}; there are {', '.join(sorted(voices))}")
    audio, sr = kokoro.create(line["text"], voice=voice, speed=float(s.get("speed", 1.0)), lang=s.get("lang", "en-us"))
    sf.write(cache / f"{line['id']}.wav", np.asarray(audio, dtype=np.float32), sr)
    print(f"{line['id']}: {voice}, {len(audio) / sr:.2f}s  {line['text']}", flush=True)
