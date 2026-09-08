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
# Param: PATCH_PASSWORD    - the value, already escaped for the sed delimiter
set -euo pipefail

: "${PATCH_VOLUME:?}"
: "${PATCH_CONFIG_REL:?}"
: "${PATCH_EXPRESSION:?}"
: "${PATCH_PASSWORD:?}"

container volume ls -q -f "name=^${PATCH_VOLUME}$" | grep -q . || exit 0

opts="$(container volume inspect --format '{{if .Options}}{{.Options.o}}{{end}}' "$PATCH_VOLUME")"
case "$opts" in
*bind*) data_dir="$(container volume inspect --format '{{.Options.device}}' "$PATCH_VOLUME")" ;;
*) data_dir="$(container volume inspect --format '{{.Mountpoint}}' "$PATCH_VOLUME")" ;;
esac

config="${data_dir}/${PATCH_CONFIG_REL}"
test -f "$config" || exit 0

expression="${PATCH_EXPRESSION//@PASSWORD@/$PATCH_PASSWORD}"

if [ -z "$(sed -E -n "${expression}p" "$config" | head -n1)" ]; then
  echo "FAILED: no line in ${PATCH_CONFIG_REL} matches the patch expression" >&2
  exit 1
fi

sed -E -i "$expression" "$config"
echo PATCHED
