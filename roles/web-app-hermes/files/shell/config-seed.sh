#!/command/with-contenv sh
# shellcheck shell=sh
# nocheck: mirrored-unit-test - runs inside the image's s6 cont-init.d stage, before
# 01-hermes-setup; there is no host-side interpreter to exercise it against

seed="${HERMES_CONFIG_SEED}"
target="${HERMES_CONFIG_TARGET}"

[ -f "$seed" ] || exit 0

if ! cp "$seed" "$target"; then
    echo "[infinito] could not seed $target from $seed" >&2
fi
exit 0
