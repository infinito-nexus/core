#!/usr/bin/env bash
set -euo pipefail
venv="${MOTION_DESIGNER_TTS_VENV:-${MOTION_DESIGNER_HOME:-$HOME/.cache/motion-designer}/chatterbox}"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
uv venv "$venv" --python 3.11
VIRTUAL_ENV="$venv" uv pip install chatterbox-tts "setuptools<81"
"$venv/bin/python" -c "import chatterbox, perth; assert perth.PerthImplicitWatermarker is not None; print('Chatterbox ready:', '$venv')"
echo "Point voiceover.py at it with MOTION_DESIGNER_TTS_PYTHON=$venv/bin/python if it is not the default path."
