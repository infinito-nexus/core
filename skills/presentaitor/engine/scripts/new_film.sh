#!/usr/bin/env bash
set -euo pipefail
dir="${1:?usage: new_film.sh <dir> [mobile|desktop|story|blank|overlay]}"
kind="${2:-mobile}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$kind" in
  mobile | desktop | story | blank | overlay) ;;
  *) echo "kind must be mobile, desktop, story, blank or overlay, not $kind" >&2; exit 2 ;;
esac
if [ -d "$dir/src" ] && [ -n "$(ls -A "$dir/src")" ]; then
  echo "$dir/src is not empty; not overwriting it" >&2
  exit 1
fi
mkdir -p "$dir/src" "$dir/audio" "$dir/out" "$dir/dist"
cp -R "$here/../templates/shared/." "$dir/src/"
cp -R "$here/../templates/$kind/." "$dir/src/"
printf 'out/\naudio/source/\n' > "$dir/.gitignore"
echo "$kind film started in $dir/src. Open $dir/src/index.html in Chrome, or run: node $here/check.mjs $dir/src/index.html"
