#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
home="${MOTION_DESIGNER_HOME:-$HOME/.cache/motion-designer}"
what="${1:?usage: install.sh <tool> [--dry-run]}"
dry=0
[ "${2:-}" = "--dry-run" ] && dry=1
has() { command -v "$1" >/dev/null 2>&1; }

run() {
  echo "+ $*"
  [ "$dry" = 1 ] || eval "$*"
}

pkg() {
  local mac="$1" deb="$2" rpm="$3" arch="$4"
  case "$(uname -s)" in
    Darwin)
      if ! has brew; then
        echo "Homebrew is not installed. Install it from https://brew.sh (it asks for your password), then run this again." >&2
        exit 1
      fi
      run "brew install $mac" ;;
    Linux)
      if has apt-get; then run "sudo apt-get update && sudo apt-get install -y $deb"
      elif has dnf; then run "sudo dnf install -y $rpm"
      elif has pacman; then run "sudo pacman -S --needed --noconfirm $arch"
      else echo "No apt-get, dnf or pacman here; install $deb with your package manager." >&2; exit 1; fi ;;
    *) echo "On Windows, use WSL2 (Ubuntu) and run this there." >&2; exit 1 ;;
  esac
}

case "$what" in
  node)
    if [ "$(uname -s)" = Linux ] && ! has brew; then
      run "curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell && \$HOME/.local/share/fnm/fnm install 22"
      echo "Open a new shell (or run: eval \"\$(\$HOME/.local/share/fnm/fnm env)\") so node 22 is on PATH."
    else
      pkg node nodejs nodejs nodejs
    fi ;;
  chrome)
    has npx || { echo "npx comes with Node; install node first (install.sh node)." >&2; exit 1; }
    run "npx -y @puppeteer/browsers install chrome-headless-shell@stable --path '$home/browsers'" ;;
  ffmpeg | ffprobe) pkg ffmpeg ffmpeg ffmpeg ffmpeg ;;
  python3) pkg python python3 python3 python ;;
  uv)
    if [ "$(uname -s)" = Darwin ] && has brew; then run "brew install uv"
    else run "curl -LsSf https://astral.sh/uv/install.sh | sh"; fi ;;
  pillow)
    if has uv; then echo "uv fetches Pillow by itself the first time a contact sheet is made; nothing to install."
    else run "python3 -m pip install --user pillow"; fi ;;
  chatterbox)
    has uv || { echo "Chatterbox's environment is built with uv; install it first (install.sh uv)." >&2; exit 1; }
    run "bash '$here/setup_tts.sh'" ;;
  kokoro)
    has uv || { echo "Kokoro's environment is built with uv; install it first (install.sh uv)." >&2; exit 1; }
    run "bash '$here/setup_kokoro.sh'" ;;
  acestep)
    has uv || { echo "ACE-Step's environment is built with uv; install it first (install.sh uv)." >&2; exit 1; }
    run "bash '$here/setup_music.sh'" ;;
  swift) run "xcode-select --install" ;;
  say) echo "say ships with macOS; on other systems use --backend chatterbox or kokoro." ;;
  *) echo "unknown tool: $what" >&2; exit 2 ;;
esac
