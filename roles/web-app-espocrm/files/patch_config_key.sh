#!/usr/bin/env sh
#
# Idempotently set a single PHP config key inside the EspoCRM container.
# Runs INSIDE the espocrm container (piped via `container exec -i ... sh < this-file`).
# Required env, supplied via `container exec -e KEY=VALUE`:
#   CONFIG_KEY    PHP array key to update (host / dbname / user / password / ...)
#   CONFIG_VALUE  desired value (raw, may contain `/`, `&`, or `|`)
#   CONFIG_FILE   absolute path to config-internal.php
# Prints `CHANGED` to stdout when the file was rewritten so the caller can
# pick that up via `changed_when: "'CHANGED' in <reg>.stdout"`.
set -eu

: "${CONFIG_KEY:?CONFIG_KEY is required}"
: "${CONFIG_FILE:?CONFIG_FILE is required}"
: "${CONFIG_VALUE?CONFIG_VALUE is required}"

if grep -q "'${CONFIG_KEY}' *=> *'${CONFIG_VALUE}'," "$CONFIG_FILE"; then
  exit 0
fi

# Escape sed replacement specials in the value so `/`, `&`, `|`, `\`
# survive verbatim regardless of which delimiter the rewrite uses.
escaped=$(printf '%s' "$CONFIG_VALUE" | sed -e 's/[\\&|]/\\&/g' -e 's:/:\\/:g')

sed -i "s/'${CONFIG_KEY}'\\s*=>\\s*[^,]*,/'${CONFIG_KEY}' => '${escaped}',/" "$CONFIG_FILE"
echo CHANGED
