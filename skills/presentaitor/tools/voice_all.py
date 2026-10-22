"""Voice, re-time, mix and remux film folders, one at a time.

Args:
    argv[1:]: film folders, each holding voiceover.json and a rendered out/<name>.mp4.

Output:
    <film>/audio/voiceover-mix.m4a and <film>/out/<name>-voiced.mp4 (picture copied, no re-render).

Chatterbox uses every CPU core, so films run sequentially: two jobs at once are roughly
100x slower, not 2x. NUMBA_CACHE_DIR and HF_HOME point at /tmp because the sandbox keeps
the venv and ~/.cache read-only; the first run downloads the weights (about 3 GB) there.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine" / "scripts"
CACHE = Path(os.environ.get("PRESENTAITOR_CACHE", "/tmp/presentaitor-cache"))
LOCAL_HF = Path.home() / ".cache" / "huggingface"
DEFAULT_HF = LOCAL_HF if (LOCAL_HF / "hub" / "models--ResembleAI--chatterbox").exists() else CACHE / "hf"
ENV = {
    **os.environ,
    "NUMBA_CACHE_DIR": str(CACHE / "numba"),
    "HF_HOME": os.environ.get("HF_HOME", str(DEFAULT_HF)),
    **({"HF_HUB_OFFLINE": "1"} if DEFAULT_HF == LOCAL_HF and "HF_HUB_OFFLINE" not in os.environ else {}),
}


def run(*args):
    return subprocess.run([str(a) for a in args], env=ENV, capture_output=True, text=True)


for film in map(Path, sys.argv[1:]):
    vo = film / "voiceover.json"
    print(f"== {film.name}", flush=True)
    first = run("python3", ENGINE / "voiceover.py", vo)
    if first.returncode != 0:
        print(f"   first pass: {(first.stderr.strip().splitlines() or ['?'])[-1]}", flush=True)
    flow = run("python3", HERE / "reflow.py", vo)
    print("   " + flow.stdout.strip().replace("\n", "\n   "), flush=True)
    if flow.returncode != 0:
        print(f"   REFLOW FAILED (a line has no take; lengthen or reword it): {flow.stderr.strip()[-300:]}", flush=True)
        continue
    final = run("python3", ENGINE / "voiceover.py", vo)
    if final.returncode != 0:
        print(f"   MIX FAILED: {final.stderr.strip()[-300:]}", flush=True)
        continue
    print("   " + next((ln for ln in final.stdout.splitlines() if ln.startswith("voice ")), "mixed"), flush=True)
    video = next(p for p in sorted((film / "out").glob("*.mp4")) if not p.stem.endswith("-voiced"))
    out = video.with_name(video.stem + "-voiced.mp4")
    mux = run("ffmpeg", "-v", "error", "-y", "-i", video, "-i", film / "audio/voiceover-mix.m4a",
              "-map", "0:v", "-map", "1:a", "-c", "copy", "-shortest", out)
    print(f"   {'OK ' + str(out) if mux.returncode == 0 else 'MUX FAILED: ' + mux.stderr[-300:]}", flush=True)
