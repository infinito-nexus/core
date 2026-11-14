#!/usr/bin/env bash
# Rewrite the database password an application persists inside its own config,
# on whichever node holds the volume. Every swarm node runs this; the ones
# without the volume, or without the config on it, leave without printing the
# marker, which is what the calling task reads as "changed".
#
# The password is injected here rather than left to the shell: the expression
# arrives as an environment variable, and a ${...} inside a variable's value is
# not expanded a second time.
#
# Param: PATCH_VOLUME      - docker volume the app persists its config in
# Param: PATCH_CONFIG_REL  - config path relative to that volume's mountpoint
# Param: PATCH_EXPRESSION  - extended-regex sed expression (sed -E), with
#                            @PASSWORD@ where the value goes
# Param: PATCH_DATA_DIR    - inventory-known backing directory, tried when the
#                            volume object does not name its own
# Param: stdin             - first line: the password, already escaped for the
#                            sed delimiter
set -euo pipefail

: "${PATCH_VOLUME:?}"
: "${PATCH_CONFIG_REL:?}"
: "${PATCH_EXPRESSION:?}"
IFS= read -r PATCH_PASSWORD || : # nocheck: shell-or-true -- read returns 1 on a last line without a newline; the next line rejects an empty value
: "${PATCH_PASSWORD:?the password arrives on stdin}"

container volume ls -q -f "name=^${PATCH_VOLUME}$" | grep -q . || exit 0

opts="$(container volume inspect --format '{{if .Options}}{{.Options.o}}{{end}}' "$PATCH_VOLUME")"
case "$opts" in
*bind*) data_dir="$(container volume inspect --format '{{.Options.device}}' "$PATCH_VOLUME")" ;;
*) data_dir="$(container volume inspect --format '{{.Mountpoint}}' "$PATCH_VOLUME")" ;;
esac

config="${data_dir}/${PATCH_CONFIG_REL}"
test -f "$config" || config="${PATCH_DATA_DIR:-}/${PATCH_CONFIG_REL}"
if [ ! -f "$config" ]; then
  echo "SKIPPED: ${PATCH_CONFIG_REL} is under neither ${data_dir} nor ${PATCH_DATA_DIR:-<unset>};" \
    "a node holding ${PATCH_VOLUME} without its driver options reports the empty node-local path"
  exit 0
fi

expression="${PATCH_EXPRESSION//@PASSWORD@/$PATCH_PASSWORD}"

if [ -z "$(printf '%sp\n' "$expression" | sed -E -n -f /dev/stdin "$config" | head -n1)" ]; then
  echo "FAILED: no line in ${PATCH_CONFIG_REL} matches the patch expression" >&2
  exit 1
fi

printf '%s\n' "$expression" | sed -E -i -f /dev/stdin "$config"
echo PATCHED
