#!/bin/sh
# Args: action (put|delete), object URL, S3 region.
# Stdin: "<access key>:<secret key>" on the first line; for put, the PNG as base64 after it.
# Prints CHANGED, UNCHANGED, REMOVED or ABSENT.
set -eu
action=$1
url=$2
region=$3
IFS= read -r credentials
config() {
  printf 'user = "%s"\naws-sigv4 = "aws:amz:%s:s3"\nurl = "%s"\nsilent\nfail\n' "$credentials" "$region" "$url"
}
if [ "$action" = delete ]; then
  if config | curl -K - --head -o /dev/null; then
    config | curl -K - -X DELETE -o /dev/null
    echo REMOVED
  else
    echo ABSENT
  fi
  exit 0
fi
body=$(mktemp)
trap 'rm -f "$body"' EXIT
base64 -d > "$body"
wanted=$(md5sum < "$body" | cut -d' ' -f1)
current=$(config | curl -K - | md5sum | cut -d' ' -f1)
if [ "$current" = "$wanted" ]; then
  echo UNCHANGED
  exit 0
fi
config | curl -K - -X PUT -H 'Content-Type: image/png' --data-binary "@$body" -o /dev/null
echo CHANGED
