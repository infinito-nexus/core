#!/bin/sh
set -eu

# Usage:
#   replace_pinned_app.sh <apps_directory> <app_id> < <release.tar.gz>
#   stdin: the release archive, holding the app under <app_id>/.
#
# Exit: 0, with [CHANGED] on stdout when <apps_directory>/<app_id> was replaced
# by the release; non-zero when the archive does not unpack or lacks
# <app_id>/appinfo/info.xml, with <apps_directory>/<app_id> left untouched.

apps_dir="$1"
app_id="$2"
live="$apps_dir/$app_id"
stage="$apps_dir/.$app_id.stage"
old="$apps_dir/.$app_id.old"

rm -rf "$stage" "$old"
mkdir "$stage"
tar -xzf - -C "$stage"
test -f "$stage/$app_id/appinfo/info.xml"

if [ -d "$live" ] && diff -rq "$live" "$stage/$app_id" >/dev/null; then
  rm -rf "$stage"
  exit 0
fi

if [ -d "$live" ]; then
  mv "$live" "$old"
fi
mv "$stage/$app_id" "$live"
rm -rf "$stage" "$old"
echo "[CHANGED] $live now holds exactly the files of the pinned $app_id release."
