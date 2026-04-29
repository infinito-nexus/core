#!/usr/bin/env bash
# shellcheck shell=bash
#
# Resolve registry-cache defaults outside compose.yml so the YAML stays
# free of magic numbers and so the cache size can adapt to the host's
# free disk space at source time. compose.yml consumes the three
# variables exported here strictly via `${VAR:?...}`; sourcing this
# file (transitively via scripts/meta/env/all.sh) is mandatory before
# any `docker compose ...` invocation that touches the `cache` profile.

set -euo pipefail

: "${INFINITO_REGISTRY_CACHE_HOST_PATH:=/var/cache/infinito/core/cache/registry/mirror}"
: "${INFINITO_REGISTRY_CACHE_CA_HOST_PATH:=/var/cache/infinito/core/cache/registry/ca}"
export INFINITO_REGISTRY_CACHE_HOST_PATH
export INFINITO_REGISTRY_CACHE_CA_HOST_PATH

# Default CACHE_MAX_SIZE to half the free disk space at the cache path
# (or its closest existing ancestor, since the path itself is created
# on first start by docker compose `bind: { create_host_path: true }`).
# The proxy treats this as a soft cap with LRU eviction, so reserving
# the OTHER half for the rest of the system keeps the host usable when
# the cache fills. Override by exporting INFINITO_REGISTRY_CACHE_MAX_SIZE
# explicitly before sourcing this file.
if [[ -z "${INFINITO_REGISTRY_CACHE_MAX_SIZE:-}" ]]; then
	_rc_path="${INFINITO_REGISTRY_CACHE_HOST_PATH}"
	while [[ ! -d "${_rc_path}" && "${_rc_path}" != "/" && "${_rc_path}" != "." ]]; do
		_rc_path="$(dirname "${_rc_path}")"
	done
	# df --output=avail -B1G prints "Avail" header + integer-GB rows.
	_rc_avail_gb="$(df --output=avail -B1G "${_rc_path}" 2>/dev/null | awk 'NR==2 {print $1+0}')"
	if [[ -z "${_rc_avail_gb}" || "${_rc_avail_gb}" -le 0 ]]; then
		# df failed or zero free space; fall back to a conservative cap
		# so the proxy still has a bounded budget instead of unbounded
		# growth into a possibly tiny tmpfs.
		_rc_avail_gb=2
	fi
	_rc_half_gb=$((_rc_avail_gb / 2))
	if [[ "${_rc_half_gb}" -lt 1 ]]; then
		_rc_half_gb=1
	fi
	INFINITO_REGISTRY_CACHE_MAX_SIZE="${_rc_half_gb}g"
	unset _rc_path _rc_avail_gb _rc_half_gb
fi
export INFINITO_REGISTRY_CACHE_MAX_SIZE
