#!/usr/bin/env bash
set -euo pipefail
dir="${MOTION_DESIGNER_ACESTEP:-${MOTION_DESIGNER_HOME:-$HOME/.cache/motion-designer}/ACE-Step-1.5}"
rev=ca1e85fe9430179831e6bc6be790c332190a3866
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
if [ ! -d "$dir/.git" ]; then
  git clone https://github.com/ace-step/ACE-Step-1.5.git "$dir"
  git -C "$dir" checkout -q "$rev"
fi
(cd "$dir" && uv sync && uv run acestep-download)
"$dir/.venv/bin/python" -c "import acestep; print('ACE-Step ready:', '$dir')"
echo "Point music_gen.py at it with MOTION_DESIGNER_ACESTEP=$dir if it is not the default path."
