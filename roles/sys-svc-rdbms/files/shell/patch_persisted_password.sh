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
# Param: PATCH_EXPRESSION  - sed expression, with @PASSWORD@ where the value goes
# Param: PATCH_PASSWORD    - the value, already escaped for the sed delimiter
set -euo pipefail

: "${PATCH_VOLUME:?}"
: "${PATCH_CONFIG_REL:?}"
: "${PATCH_EXPRESSION:?}"
: "${PATCH_PASSWORD:?}"

container volume ls -q -f "name=^${PATCH_VOLUME}$" | grep -q . || exit 0

mountpoint="$(container volume inspect --format '{{.Mountpoint}}' "$PATCH_VOLUME")"
config="${mountpoint}/${PATCH_CONFIG_REL}"
test -f "$config" || exit 0

sed -i "${PATCH_EXPRESSION//@PASSWORD@/$PATCH_PASSWORD}" "$config"
echo PATCHED
