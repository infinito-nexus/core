#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
home="${MOTION_DESIGNER_HOME:-$HOME/.cache/motion-designer}"
json=0
[ "${1:-}" = "--json" ] && json=1
rows=()
missing_required=()

add() {
  rows+=("$1|$2|$3|$4|$5")
  if [ "$2" != ok ] && [ "$4" = required ]; then missing_required+=("$1"); fi
}
has() { command -v "$1" >/dev/null 2>&1; }

if has node; then
  v=$(node -p 'process.versions.node')
  if [ "${v%%.*}" -ge 22 ]; then add node ok "$v" required "headless Chrome driver, renders, checks"
  else add node old "$v" required "Node 22 or newer (built-in WebSocket and fetch)"; fi
else
  add node missing "" required "headless Chrome driver, renders, checks (Node 22+)"
fi

chrome=""
if has node; then
  chrome=$(node --input-type=module -e "import { CHROME } from '$here/cdp.mjs'; console.log(CHROME || '')" 2>/dev/null || true)
fi
if [ -n "$chrome" ]; then add chrome ok "$("$chrome" --version 2>/dev/null | grep -Eo '[0-9]+(\.[0-9]+)+' | head -1)" required "draws every frame: $chrome"
else add chrome missing "" required "draws every frame (Chrome, Chromium or Chrome for Testing)"; fi

for tool in ffmpeg ffprobe; do
  if has "$tool"; then add "$tool" ok "$("$tool" -version 2>/dev/null | head -1 | awk '{print $3}')" required "video encoding, audio cuts and mixes"
  else add "$tool" missing "" required "video encoding, audio cuts and mixes"; fi
done

if has python3 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  add python3 ok "$(python3 -c 'import platform; print(platform.python_version())')" required "music analysis, cuts, voiceover, single-file build"
else
  add python3 missing "" required "music analysis, cuts, voiceover, single-file build (Python 3.9+)"
fi

if has uv; then add uv ok "$(uv --version | awk '{print $2}')" recommended "fetches Python packages on first use (Pillow, Chatterbox, Kokoro)"
else add uv missing "" recommended "fetches Python packages on first use (Pillow, Chatterbox, Kokoro)"; fi

if has python3 && python3 -c 'import PIL' 2>/dev/null; then add pillow ok "$(python3 -c 'import PIL; print(PIL.__version__)')" recommended "contact sheets"
elif has uv; then add pillow ok "via uv" recommended "contact sheets"
else add pillow missing "" recommended "contact sheets"; fi

if [ "$(uname -s)" = Darwin ]; then
  if has swift; then add swift ok "$(swift --version 2>&1 | head -1 | sed -E 's/.*version ([0-9.]+).*/\1/')" optional "SF Symbols for iOS and macOS apps"
  else add swift missing "" optional "SF Symbols for iOS and macOS apps"; fi
  if has say; then add say ok "macOS" optional "voiceover drafts"; else add say missing "" optional "voiceover drafts"; fi
fi

tts="${MOTION_DESIGNER_TTS_PYTHON:-$home/chatterbox/bin/python}"
if [ -x "$tts" ]; then add chatterbox ok "installed" optional "natural voiceover: $tts"
else add chatterbox missing "" optional "natural voiceover (local, about 4 GB)"; fi

kokoro="${MOTION_DESIGNER_KOKORO_PYTHON:-$home/kokoro/bin/python}"
if [ -x "$kokoro" ]; then add kokoro ok "installed" optional "light voiceover: $kokoro"
else add kokoro missing "" optional "light voiceover, preset voices (local, about 0.6 GB)"; fi

ace="${MOTION_DESIGNER_ACESTEP:-$home/ACE-Step-1.5}"
if [ -n "${MOTION_DESIGNER_ACESTEP_URL:-}" ]; then
  if curl -fsS -m 5 "$MOTION_DESIGNER_ACESTEP_URL/health" >/dev/null 2>&1; then add acestep ok "server" optional "original music on $MOTION_DESIGNER_ACESTEP_URL"
  else add acestep missing "" optional "original music: no answer from $MOTION_DESIGNER_ACESTEP_URL"; fi
elif [ -x "$ace/.venv/bin/python" ] && [ -d "$ace/checkpoints/acestep-v15-turbo" ]; then add acestep ok "installed" optional "original music: $ace"
else add acestep missing "" optional "original music, made locally (about 11 GB)"; fi

if [ "$json" = 1 ]; then
  printf '['
  for i in "${!rows[@]}"; do
    IFS='|' read -r name status version need what <<< "${rows[$i]}"
    fix=""
    [ "$status" != ok ] && fix="bash $here/install.sh $name"
    [ "$i" -gt 0 ] && printf ','
    printf '{"name":"%s","status":"%s","version":"%s","need":"%s","for":"%s","install":"%s"}' "$name" "$status" "$version" "$need" "$what" "$fix"
  done
  printf ']\n'
else
  echo "motion-designer doctor"
  for row in "${rows[@]}"; do
    IFS='|' read -r name status version need what <<< "$row"
    mark="✓"; [ "$status" != ok ] && mark="✗"
    line=$(printf '  %s %-11s %-12s %-16s %s' "$mark" "$name" "$need" "${version:0:16}" "$what")
    [ "$status" != ok ] && line="$line  →  bash $here/install.sh $name"
    echo "$line"
  done
  if [ ${#missing_required[@]} -eq 0 ]; then echo "everything required is here"
  else echo "missing (required): ${missing_required[*]}"; fi
fi
[ ${#missing_required[@]} -eq 0 ]
