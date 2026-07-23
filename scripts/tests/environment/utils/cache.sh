#!/usr/bin/env bash
# Cache-stack assertions and probes for the environment test suite.
# Verifies that BOTH the registry-cache and the package-cache (Nexus +
# nginx frontend) actually serve traffic during a deploy, including
# the DiD inner-build path that the runner-side traffic alone does
# NOT exercise.
#
# This file is sourced ON TOP OF common.sh by callers that need cache
# checks.
set -euo pipefail

# Map runtime image to the Nexus proxy repo that proxies its system
# package manager. Empty string means no system-level proxy is wired
# for that runtime (e.g. Arch / Manjaro use pacman, which is not
# cached). Echoes the proxy name on stdout.
expected_system_proxy_for_runtime() {
	local image="${DEV_RUNTIME_IMAGE:-}"
	case "${image}" in
	*debian*) echo "apt-debian" ;;
	*ubuntu*) echo "apt-ubuntu" ;;
	*fedora*) echo "yum-fedora" ;;
	*centos* | *rocky*) echo "yum-rocky" ;;
	*) echo "" ;;
	esac
}

# Count Nexus request-log entries for a given proxy repo, or for any
# repo when the argument is empty. Filters out health-probe, admin,
# and UI traffic so the count reflects real pull-through activity.
nexus_repo_requests() {
	local repo="${1:-}"
	local pattern
	if [[ -n "${repo}" ]]; then
		pattern="\"(GET|HEAD|POST|PUT) /repository/${repo}/"
	else
		pattern="\"(GET|HEAD|POST|PUT) /repository/[^/ ]+/"
	fi
	docker exec infinito-package-cache sh -c \
		"grep -cE '${pattern}' /nexus-data/log/request.log 2>/dev/null || echo 0" \
		2>/dev/null | awk '{print $1+0}'
}

# Count registry-cache flow entries (HIT, MISS, REVALIDATED, UPDATING,
# STALE). Both HIT and MISS prove the cache layer is engaged; counting
# only HITs misses cold deploys where everything is a first pull.
registry_cache_flows() {
	docker logs infinito-registry-cache 2>&1 |
		grep -cE '"upstream_cache_status":"(HIT|MISS|REVALIDATED|UPDATING|STALE)"' ||
		true
}

# Snapshot all cache counters relevant for the AND-assertion. Output
# is a single space-separated line consumed by ``assert_caches_used``.
# Order matters: total-nexus, expected-distro-proxy, registry-flows.
cache_snapshot() {
	local nexus_total proxy_count registry_flows expected_proxy
	expected_proxy="$(expected_system_proxy_for_runtime)"
	nexus_total="$(nexus_repo_requests "")"
	proxy_count="$(nexus_repo_requests "${expected_proxy}")"
	registry_flows="$(registry_cache_flows)"
	printf '%s %s %s\n' \
		"${nexus_total:-0}" "${proxy_count:-0}" "${registry_flows:-0}"
}

# Assert that BOTH cache stacks were engaged during the deploy. Fails
# loudly if either stack is silent and reports a per-cache breakdown
# so the operator can see which side regressed.
#
# Usage: assert_caches_used <before> <after>
#   where <before> and <after> are the strings returned by
#   ``cache_snapshot`` (3 fields each).
assert_caches_used() {
	local before="${1}" after="${2}"
	local nexus_total_before proxy_before registry_before
	local nexus_total_after proxy_after registry_after
	read -r nexus_total_before proxy_before registry_before <<<"${before}"
	read -r nexus_total_after proxy_after registry_after <<<"${after}"

	local delta_nexus_total=$((nexus_total_after - nexus_total_before))
	local delta_proxy=$((proxy_after - proxy_before))
	local delta_registry=$((registry_after - registry_before))
	local expected_proxy
	expected_proxy="$(expected_system_proxy_for_runtime)"

	echo "[cache] package proxy requests (any repo) +${delta_nexus_total}" \
		"(now ${nexus_total_after})"
	if [[ -n "${expected_proxy}" ]]; then
		echo "[cache] package proxy '${expected_proxy}' +${delta_proxy}" \
			"(now ${proxy_after})"
	else
		echo "[cache] no Nexus system-proxy mapped for" \
			"DEV_RUNTIME_IMAGE='${DEV_RUNTIME_IMAGE:-?}'; skipping per-proxy check"
	fi
	echo "[cache] registry-cache flows (HIT|MISS|...) +${delta_registry}" \
		"(now ${registry_after})"

	local -a failures=()

	if [[ "${nexus_total_after}" -le 0 ]]; then
		failures+=("package-cache: no /repository/<name>/ traffic ever observed (Nexus seems unused)")
	fi
	if [[ -n "${expected_proxy}" && "${proxy_after}" -le 0 ]]; then
		failures+=("package-cache: expected proxy '${expected_proxy}' for ${DEV_RUNTIME_IMAGE} has no cached requests")
	fi

	if [[ "${delta_registry}" -le 0 ]]; then
		failures+=("registry-cache: no HIT/MISS recorded during this deploy")
	fi

	if ((${#failures[@]} > 0)); then
		echo "[FAIL] cache assertions:" >&2
		printf '  - %s\n' "${failures[@]}" >&2
		exit 1
	fi
	echo "[OK] both cache stacks observed activity (registry + package-cache, including '${expected_proxy:-N/A}')"
}

# Resolve the Fedora release number for the configured runtime image
# by reading $VERSION_ID from /etc/os-release inside the image. We do
# this dynamically because hardcoding `releases/<N>/...` rots the moment
# the pinned Fedora release reaches EOL and dl.fedoraproject.org stops
# serving it (the previous hardcode of 40 broke when Fedora 40 went EOL
# in May 2025). Echoes the version on stdout, or empty on failure.
_resolve_fedora_release() {
	local image="${DEV_RUNTIME_IMAGE:-}"
	[[ -z "${image}" ]] && return 0
	docker run --rm --entrypoint /bin/cat "${image}" /etc/os-release 2>/dev/null |
		awk -F= '/^VERSION_ID=/ { gsub(/"/, "", $2); print $2; exit }'
}

# Map runtime image to a (proxy, upstream-path) pair that the active
# probe can fetch through Nexus. The path picks a small, reliably-
# available index file on the upstream so the probe stays cheap.
_probe_target_for_runtime() {
	local image="${DEV_RUNTIME_IMAGE:-}"
	local fedora_ver
	case "${image}" in
	*debian*) echo "apt-debian dists/bookworm/Release" ;;
	*ubuntu*) echo "apt-ubuntu dists/jammy/Release" ;;
	*fedora*)
		fedora_ver="$(_resolve_fedora_release)"
		if [[ -z "${fedora_ver}" ]]; then
			echo ""
		else
			echo "yum-fedora releases/${fedora_ver}/Everything/x86_64/os/repodata/repomd.xml"
		fi
		;;
	*centos* | *rocky*) echo "yum-rocky 9/BaseOS/x86_64/os/repodata/repomd.xml" ;;
	*) echo "" ;;
	esac
}

# Active end-to-end probe: hit each cache through its public surface
# and verify the request reaches the cache and is logged as proxy
# traffic. Catches regressions where the cache stack is up but stops
# proxying (mis-routed nginx, dead upstream, broken auth, expired CA,
# etc.). Calls ``exit 1`` if either probe fails.
probe_caches() {
	local probe_target proxy_repo upstream_path
	probe_target="$(_probe_target_for_runtime)"
	if [[ -z "${probe_target}" ]]; then
		echo "[probe] no probe target mapped for" \
			"DEV_RUNTIME_IMAGE='${DEV_RUNTIME_IMAGE:-?}'; skipping package probe"
	else
		read -r proxy_repo upstream_path <<<"${probe_target}"
		echo "[probe] package-cache: GET /repository/${proxy_repo}/${upstream_path}"
		if ! docker exec infinito-package-cache curl \
			--silent --fail --show-error --max-time 60 \
			--output /dev/null \
			"http://localhost:8081/repository/${proxy_repo}/${upstream_path}"; then
			echo "[FAIL] package-cache: proxy '${proxy_repo}' did not serve" \
				"'${upstream_path}'. The cache stack is up but pull-through is broken." >&2
			exit 1
		fi
		echo "[OK] package-cache: '${proxy_repo}' served '${upstream_path}'"
	fi

	echo "[probe] registry-cache: GET /ca.crt"
	if ! docker exec infinito-registry-cache wget \
		--quiet --tries=1 --timeout=10 \
		--output-document=/dev/null \
		"http://127.0.0.1:3128/ca.crt"; then
		echo "[FAIL] registry-cache: /ca.crt did not respond. The cache" \
			"container is unhealthy." >&2
		exit 1
	fi
	echo "[OK] registry-cache: /ca.crt responded"
}

# Active DiD probe: drive a throwaway ``docker build`` whose
# ``apt-get update`` MUST flow through the package-cache frontend
# (``deb.debian.org`` is hijacked via ``--add-host`` to the frontend
# IP, exactly mirroring the runtime override that
# ``roles/sys-svc-compose/files/compose.py`` injects for app builds).
# Verifies the inner-build / DiD cache path, which the
# Ansible-driven runner-side traffic alone does NOT exercise.
probe_did_inner_build() {
	local frontend_ip
	frontend_ip="${INFINITO_CACHE_PACKAGE_FRONTEND_IP:-}"
	if [[ -z "${frontend_ip}" ]]; then
		echo "[probe-did] INFINITO_CACHE_PACKAGE_FRONTEND_IP unset; skipping DiD probe"
		return 0
	fi

	local network="${COMPOSE_NETWORK:-}"
	if [[ -z "${network}" ]]; then
		network="$(docker inspect -f \
			'{{range $k,$_ := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' \
			infinito-package-cache-frontend 2>/dev/null |
			head -n1)"
	fi
	if [[ -z "${network}" ]]; then
		echo "[FAIL] DiD probe: could not discover compose network for" \
			"infinito-package-cache-frontend (container missing or not connected)" >&2
		exit 1
	fi
	local before after delta tmpdir tag rc=0
	before="$(docker logs infinito-package-cache-frontend 2>&1 | wc -l)"

	tmpdir="$(mktemp -d)"
	cat >"${tmpdir}/Dockerfile" <<-'EOF'
		FROM debian:bookworm-slim
		RUN apt-get update -o Acquire::http::No-Cache=true
	EOF
	tag="cache-did-probe-$$"

	echo "[probe-did] docker build --add-host deb.debian.org:${frontend_ip}" \
		"--network ${network} (apt-get update via frontend)"
	if ! DOCKER_BUILDKIT=0 docker build --no-cache \
		--network "${network}" \
		--add-host "deb.debian.org:${frontend_ip}" \
		-t "${tag}" "${tmpdir}" 2>&1 | tail -10; then
		rc=1
	fi
	rm -rf "${tmpdir}"
	docker rmi "${tag}" >/dev/null 2>&1 || true

	if [[ "${rc}" -ne 0 ]]; then
		echo "[FAIL] DiD probe: docker build failed (frontend, network or upstream broken)" >&2
		exit 1
	fi

	after="$(docker logs infinito-package-cache-frontend 2>&1 | wc -l)"
	delta=$((after - before))
	if [[ "${delta}" -le 0 ]]; then
		echo "[FAIL] DiD probe: build succeeded but frontend logged no new requests" >&2
		echo "       (extra_hosts hijack or nginx upstream rewrite is broken)" >&2
		exit 1
	fi
	echo "[OK] DiD inner-build flowed through cache frontend (+${delta} log lines)"
}
