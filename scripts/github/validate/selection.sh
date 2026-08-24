#!/usr/bin/env bash
#
# Validate a run's selection inputs against the branch it would deploy from,
# before any runner is spent on it.
#
# Inputs via env:
#   INPUT_WHITELIST   whitelist value of the run ('' = nothing to check)
#   INPUT_PRIORITY    priority line of the run ('' = nothing to check)
#   INPUT_MODE        deploy modes the run draws from
#   INPUT_TOR         tor axis of the run
#   INPUT_DISTROS     distro pool of the run ('' = every declared distro)
#   INPUT_FILESYSTEM  filesystem pool of the run ('' = every declared kind)
#   INPUT_LIFECYCLES  lifecycle envelope of the run
#
# Exits non-zero when a token names a row this branch does not have or pins an
# axis the row cannot take; cli.meta.ci.validate reports every offender at once,
# so a stale list is fixed in one pass rather than one CI round per entry.

set -euo pipefail

# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

"${PYTHON}" -m cli.meta.ci.validate \
	--whitelist "${INPUT_WHITELIST:-}" \
	--priority "${INPUT_PRIORITY:-}" \
	--modes "${INPUT_MODE:-auto}" \
	--tor "${INPUT_TOR:-auto}" \
	--distros "${INPUT_DISTROS:-}" \
	--filesystem "${INPUT_FILESYSTEM:-}" \
	--lifecycles "${INPUT_LIFECYCLES:-}"
