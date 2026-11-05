#!/usr/bin/env bash
set -euo pipefail
home="${MOTION_DESIGNER_HOME:-$HOME/.cache/motion-designer}"
venv="${MOTION_DESIGNER_KOKORO_VENV:-$home/kokoro}"
models="${MOTION_DESIGNER_KOKORO_MODELS:-$venv/models}"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
uv venv "$venv" --python 3.12
VIRTUAL_ENV="$venv" uv pip install kokoro-onnx soundfile
mkdir -p "$models"
base=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
for file in kokoro-v1.0.onnx voices-v1.0.bin; do
  [ -s "$models/$file" ] || curl -fL --retry 3 -o "$models/$file" "$base/$file"
done
"$venv/bin/python" -c "from kokoro_onnx import Kokoro; k = Kokoro('$models/kokoro-v1.0.onnx', '$models/voices-v1.0.bin'); print('Kokoro ready:', len(k.get_voices()), 'voices in', '$venv')"
echo "Point voiceover.py at it with MOTION_DESIGNER_KOKORO_PYTHON=$venv/bin/python (and MOTION_DESIGNER_KOKORO_MODELS=$models) if it is not the default path."
