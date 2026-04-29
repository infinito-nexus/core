#!/usr/bin/env bash
# shellcheck shell=bash
#
# Resolve package-cache (Sonatype Nexus 3 OSS) defaults outside
# compose.yml so the YAML stays free of magic numbers and so JVM heap,
# direct memory, and blobstore quotas can adapt to the host's real RAM
# and free disk space at source time. compose.yml consumes these
# variables strictly via `${VAR:?...}`; sourcing this file (transitively
# via scripts/meta/env/all.sh) is mandatory before any
# `docker compose ...` invocation that touches the `cache` profile.
#
# See docs/requirements/012-package-cache-nexus3-oss.md.

set -euo pipefail

: "${INFINITO_PACKAGE_CACHE_HOST_PATH:=/var/cache/infinito/core/cache/package/data}"
export INFINITO_PACKAGE_CACHE_HOST_PATH

# JVM heap derived from free RAM. Nexus 3 OSS minimum is 1 GiB (-Xms /
# -Xmx). Leave half the free RAM for the rest of the system, cap at 2g
# to keep pull-through caching from monopolising the dev box. Override
# by exporting INFINITO_PACKAGE_CACHE_HEAP explicitly before sourcing.
if [[ -z "${INFINITO_PACKAGE_CACHE_HEAP:-}" ]]; then
	_pc_avail_ram_mb="$(awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
	if [[ "${_pc_avail_ram_mb}" -le 0 ]]; then
		_pc_heap_gb=1
	else
		_pc_heap_gb=$((_pc_avail_ram_mb / 2048))
		if [[ "${_pc_heap_gb}" -lt 1 ]]; then _pc_heap_gb=1; fi
		if [[ "${_pc_heap_gb}" -gt 2 ]]; then _pc_heap_gb=2; fi
	fi
	INFINITO_PACKAGE_CACHE_HEAP="${_pc_heap_gb}g"
	unset _pc_avail_ram_mb _pc_heap_gb
fi
export INFINITO_PACKAGE_CACHE_HEAP

# MaxDirectMemorySize. Nexus sizing guide recommends matching heap; 1g
# floor preserves the documented minimum.
if [[ -z "${INFINITO_PACKAGE_CACHE_DIRECT_MEM:-}" ]]; then
	INFINITO_PACKAGE_CACHE_DIRECT_MEM="${INFINITO_PACKAGE_CACHE_HEAP}"
fi
export INFINITO_PACKAGE_CACHE_DIRECT_MEM

# Blobstore quota: half the free disk space at the cache path (or its
# closest existing ancestor, since the path is created on first start
# by docker compose `bind: { create_host_path: true }`). 2g floor keeps
# the cache useful even on tight dev hosts.
if [[ -z "${INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX:-}" ]]; then
	_pc_path="${INFINITO_PACKAGE_CACHE_HOST_PATH}"
	while [[ ! -d "${_pc_path}" && "${_pc_path}" != "/" && "${_pc_path}" != "." ]]; do
		_pc_path="$(dirname "${_pc_path}")"
	done
	_pc_avail_gb="$(df --output=avail -B1G "${_pc_path}" 2>/dev/null | awk 'NR==2 {print $1+0}')"
	if [[ -z "${_pc_avail_gb}" || "${_pc_avail_gb}" -le 0 ]]; then _pc_avail_gb=4; fi
	_pc_half_gb=$((_pc_avail_gb / 2))
	if [[ "${_pc_half_gb}" -lt 2 ]]; then _pc_half_gb=2; fi
	INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX="${_pc_half_gb}g"
	unset _pc_path _pc_avail_gb _pc_half_gb
fi
export INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX

# Admin password rotation target. Operator-supplied in production-like
# setups; for local dev we synthesise a stable per-host password if
# unset so re-runs do not regenerate a different one each time. Use
# the `hostname` command (NOT the $HOSTNAME shell var) so the value is
# identical across interactive shells, non-interactive subshells, and
# Python subprocesses — $HOSTNAME is set by bash on startup but not
# always exported, which previously gave two different passwords
# (real hostname vs. the "local" fallback) for the same host.
if [[ -z "${INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD:-}" ]]; then
	_pc_host="$(hostname 2>/dev/null || echo local)"
	_pc_seed="${INFINITO_PACKAGE_CACHE_HOST_PATH}:${_pc_host}"
	INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD="$(printf '%s' "${_pc_seed}" | sha256sum | awk '{print substr($1,1,32)}')"
	unset _pc_seed _pc_host
fi
export INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD

# Host-side port for Nexus 3 UI / REST (default 8081 inside the
# container). Published bound to BIND_IP only so the proxy is not
# reachable from the public network. Override if 8081 collides on the
# host.
: "${INFINITO_PACKAGE_CACHE_PORT:=8081}"
export INFINITO_PACKAGE_CACHE_PORT
