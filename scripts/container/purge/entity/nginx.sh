#!/usr/bin/env bash
# nginx vhost purge for stacks (entity-keyed).
#
# Removes the per-domain vhost files belonging to every app under each
# given compose entity. Driven by the app-keyed orchestrator
# `purge/apps.sh` as a sibling of `db.sh`, `compose.sh`, `dir.sh` — a
# stack that drops out of a matrix-deploy round would otherwise leave
# stale vhosts behind and the next round's HTTPS probe would see HTTP
# 502 (nginx still serves the vhost but the container was pruned)
# instead of the expected TLS-error 000.
#
# All resolution and filesystem work lives in
# `utils.cleanup.nginx_vhosts` so the bash side stays a thin wrapper.
#
# Usage:
#   ./purge/entity/nginx.sh <STACK1> [STACK2] [...]
#
# Env:
#   NGINX_DIR  Base nginx config dir inside the container.
#              Default: /etc/nginx (matches svc-prx-openresty/meta/volumes.yml).
#   DOMAIN              DOMAIN_PRIMARY used to render Jinja in roles/<role>/meta/server.yml.
#              Default: infinito.test.

set -euo pipefail

if [[ "$#" -lt 1 ]]; then
	echo "ERROR: No stack names provided." >&2
	exit 2
fi

: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR must be set by the container environment}"
cd "${INFINITO_SRC_DIR}"

if [[ -f "scripts/meta/env/load.sh" ]]; then
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
fi
python_bin="${PYTHON:-python3}"

exec "${python_bin}" -m utils.cleanup.nginx_vhosts "$@"
