# Setup

The motion-designer scripts need a few programs. Find out what this machine has, tell the user what is missing and why, and install only what they agree to.

## 1. Check

```bash
bash $SKILL_DIR/scripts/doctor.sh          # a table; exit 1 if something required is missing
bash $SKILL_DIR/scripts/doctor.sh --json   # the same, to read
```

| Tool | Need | For |
|---|---|---|
| node (22+) | required | driving headless Chrome, renders, checks |
| chrome | required | drawing every frame (Chrome, Chromium, or Chrome for Testing) |
| ffmpeg, ffprobe | required | video encoding, audio cuts and mixes |
| python3 (3.9+) | required | music analysis, cuts, voiceover, single-file build |
| uv | recommended | fetches Python packages on first use: Pillow for contact sheets, Chatterbox for voices |
| pillow | recommended | contact sheets (automatic with uv) |
| swift | optional, macOS | SF Symbols for iOS and macOS apps |
| say | optional, macOS | voiceover drafts |
| chatterbox | optional | the most natural voiceover, local (about 4 GB) |
| kokoro | optional | a light voiceover with preset voices, local (about 0.6 GB) |
| acestep | optional | original music made for the film, locally (about 11 GB) or on a GPU machine that runs ACE-Step |

Optional tools matter only when the film needs them: don't offer Chatterbox or Kokoro unless a voiceover is wanted (then let the user pick one, see [voiceover](voiceover.md)), ACE-Step unless the film needs a track the user doesn't have, or Swift unless the app uses SF Symbols.

## 2. Ask

Put everything missing into one question: each item, what it is for, what the install does (the exact command from `install.sh <tool> --dry-run`, its rough download size, whether it asks for a password), and a recommended default. For example: "Install ffmpeg with Homebrew (`brew install ffmpeg`, ~100 MB) and Chrome for Testing into ~/.cache/motion-designer (~120 MB, no admin rights)?"

Never install without a yes. If they decline, say which steps won't work, and continue with what does (a film can be built and checked without ffmpeg; it can't be rendered to video).

## 3. Install and re-check

```bash
bash $SKILL_DIR/scripts/install.sh <tool>          # node | chrome | ffmpeg | python3 | uv | pillow | chatterbox | kokoro | acestep | swift
bash $SKILL_DIR/scripts/doctor.sh
```

- macOS installs go through Homebrew; if Homebrew itself is missing, give the user the link (https://brew.sh). Its installer asks for their password, so they run it.
- Linux installs use the distribution's package manager with sudo: tell the user before it asks for a password. Node on Linux comes from fnm (a per-user Node 22).
- Chrome for Testing lands in `$MOTION_DESIGNER_HOME/browsers` (default `~/.cache/motion-designer`) and the scripts find it there; `CHROME=/path/to/chrome` overrides everything.
- Chatterbox gets its own Python 3.11 environment in `$MOTION_DESIGNER_HOME/chatterbox` (PyTorch and the model weights, about 4 GB, downloaded once; a voice with `"sample": "turbo"` also fetches Chatterbox Turbo, about 4 GB more). `MOTION_DESIGNER_TTS_PYTHON` points the scripts at an existing one.
- Kokoro gets a small Python 3.12 environment in `$MOTION_DESIGNER_HOME/kokoro` with kokoro-onnx and the Kokoro-82M model files from the kokoro-onnx releases (about 0.6 GB). `MOTION_DESIGNER_KOKORO_PYTHON` and `MOTION_DESIGNER_KOKORO_MODELS` point the scripts at an existing one.
- ACE-Step 1.5 is cloned into `$MOTION_DESIGNER_HOME/ACE-Step-1.5` with its own uv environment and its models (about 11 GB, from Hugging Face, once). `MOTION_DESIGNER_ACESTEP` points the scripts at an existing checkout; `MOTION_DESIGNER_ACESTEP_URL` at an ACE-Step server on another machine instead, and then nothing is installed here.
- Windows: run everything in WSL2 (Ubuntu).

Report the final `doctor.sh` table in one line per change.
