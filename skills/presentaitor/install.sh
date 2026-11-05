#!/usr/bin/env bash
# Param: --yes       answer yes to every question (unattended install)
# Param: --no-voice  skip Chatterbox (about 4 GB); films still build, narration needs it later
# Param: --kokoro    also install Kokoro (about 0.6 GB) for quick timing drafts
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
engine="$here/engine/scripts"
yes=0 voice=1 kokoro=0
for arg in "$@"; do
  case "$arg" in
    --yes) yes=1 ;;
    --no-voice) voice=0 ;;
    --kokoro) kokoro=1 ;;
    -h|--help) sed -n '2,4p' "$0" | sed 's/^# Param: /  /'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

has() { command -v "$1" >/dev/null 2>&1; }
say() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
ask() {
  [ "$yes" = 1 ] && return 0
  read -r -p "  $1 [Y/n] " reply
  case "$reply" in [nN]*) return 1 ;; *) return 0 ;; esac
}

if [ "$(uname -s)" != Linux ] || ! has apt-get; then
  echo "This installer covers Ubuntu and Debian. Elsewhere, follow README.md and run engine/scripts/doctor.sh." >&2
  exit 1
fi

say "System packages"
pkgs=()
has ffmpeg || pkgs+=(ffmpeg)
python3 -c "import PIL" 2>/dev/null || pkgs+=(python3-pil)
fc-list 2>/dev/null | grep -qi "Inter" || pkgs+=(fonts-inter)
has unzip || pkgs+=(unzip)
has curl || pkgs+=(curl)
dpkg -s gstreamer1.0-libav >/dev/null 2>&1 || pkgs+=(gstreamer1.0-libav)
if [ "${#pkgs[@]}" -eq 0 ]; then
  ok "ffmpeg, Pillow, Inter, unzip, curl, AAC playback already installed"
elif ask "Install ${pkgs[*]} with sudo apt?"; then
  sudo apt-get update
  sudo apt-get install -y "${pkgs[@]}"
fi

say "Node.js 22+"
node_major="$(node -v 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/' || true)"
if [ -n "$node_major" ] && [ "$node_major" -ge 22 ]; then
  ok "node $(node -v)"
elif ask "Install Node 22 (fnm, in your home folder, no sudo)?"; then
  bash "$engine/install.sh" node
fi

say "uv"
if has uv; then ok "uv $(uv --version | cut -d' ' -f2)"; elif ask "Install uv?"; then bash "$engine/install.sh" uv; fi

say "Chrome for rendering"
if bash "$engine/doctor.sh" 2>/dev/null | grep -q '✓ chrome'; then
  ok "chrome found"
elif ask "Install Chrome for Testing (about 150 MB, no sudo)?"; then
  bash "$engine/install.sh" chrome
fi

say "JetBrains Mono"
if fc-list 2>/dev/null | grep -qi "JetBrains Mono"; then
  ok "JetBrains Mono found"
elif ask "Download JetBrains Mono into ~/.local/share/fonts?"; then
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/jbm.zip" https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip
  mkdir -p "$HOME/.local/share/fonts/JetBrainsMono"
  unzip -qo "$tmp/jbm.zip" 'fonts/ttf/*' -d "$tmp"
  cp "$tmp"/fonts/ttf/*.ttf "$HOME/.local/share/fonts/JetBrainsMono/"
  fc-cache -f >/dev/null
  rm -rf "$tmp"
fi

if [ "$voice" = 1 ]; then
  say "Chatterbox narrator voice (about 4 GB, plus about 3 GB of weights on first use)"
  if bash "$engine/doctor.sh" 2>/dev/null | grep -q '✓ chatterbox'; then
    ok "chatterbox installed"
  elif ask "Install Chatterbox?"; then
    bash "$engine/install.sh" chatterbox
  fi
fi
if [ "$kokoro" = 1 ]; then
  say "Kokoro draft voices"
  bash "$engine/install.sh" kokoro
fi

say "Sound in mpv"
conf="$HOME/.config/mpv/mpv.conf"
if has mpv && ! grep -qs '^ao=' "$conf"; then
  if ask "Send mpv audio through PulseAudio (fixes silent playback on PipeWire)?"; then
    mkdir -p "$(dirname "$conf")"
    echo 'ao=pulse,alsa' >> "$conf"
  fi
else
  ok "nothing to do"
fi

say "Link the skill into Claude Code"
target="$HOME/.claude/skills/presentaitor"
if [ -e "$target" ]; then
  ok "$target already exists"
else
  mkdir -p "$HOME/.claude/skills"
  ln -s "$here" "$target"
  ok "linked $target"
fi

say "Check"
bash "$engine/doctor.sh" || true
echo
echo "Done. Restart Claude Code and type /presentaitor."
