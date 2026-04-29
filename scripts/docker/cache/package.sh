#!/usr/bin/env bash
# shellcheck shell=bash
#
# Idempotent bootstrap for the Sonatype Nexus 3 OSS proxy repositories
# served by the `package-cache` compose service. Invoked from
# cli/deploy/development/up.py after the stack is healthy whenever the
# `cache` profile is active.
#
# Reads the auto-generated admin password from the bind-mounted
# /nexus-data, rotates it to ${INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD},
# creates one default blobstore with quota
# ${INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX}, and creates the MVP set of
# proxy repositories. Repeated invocations no-op once the system is
# converged.
#
# See docs/requirements/012-package-cache-nexus3-oss.md.

set -euo pipefail

: "${INFINITO_PACKAGE_CACHE_HOST_PATH:?Source scripts/meta/env/cache/package.sh first}"
: "${INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD:?Source scripts/meta/env/cache/package.sh first}"
: "${INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX:?Source scripts/meta/env/cache/package.sh first}"

# All REST calls go through `docker exec` against the package-cache
# container's curl. This sidesteps host-vs-sandbox network namespace
# differences (the published port is reachable from a normal host
# shell but not from the sandbox the dev tooling may run in) and
# avoids depending on whether BIND_IP forwards to localhost. The
# nexus3 UBI image ships curl, not wget.
PKGCACHE_CONTAINER="infinito-package-cache"
NEXUS_REST="http://127.0.0.1:8081/service/rest"

# Marker file lives INSIDE the container at /nexus-data, not at the
# host bind-mount path. Writing through `docker exec` works regardless
# of host-side sandbox restrictions on /var/cache; the bind-mount means
# the file is still visible from the host for inspection.
BOOTSTRAP_DONE_FILE="/nexus-data/.infinito-bootstrap-done"

# Default admin password baked into Nexus when
# `NEXUS_SECURITY_RANDOMPASSWORD=false` (set in compose.yml). The
# helper logs in with this on first boot and rotates to the operator's
# INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD so subsequent calls authenticate
# with the configured value. Random-password mode is unusable here
# because Nexus auto-completes onboarding silently and leaves no
# readable secret on disk for an automated bootstrap to pick up.
NEXUS_DEFAULT_PASSWORD="admin123"

log() { printf '[package-cache-bootstrap] %s\n' "$*" >&2; }

nexus_curl() { docker exec "${PKGCACHE_CONTAINER}" curl "$@"; }

# Wait until Nexus's REST API answers 200 on /v1/status. Compose
# already gates infinito on package-cache health, but bootstrap can
# also be called manually before infinito starts; the wait keeps
# both paths reliable.
wait_for_nexus() {
	local _attempt
	for _attempt in $(seq 1 120); do
		if nexus_curl -fsS "${NEXUS_REST}/v1/status" >/dev/null 2>&1; then
			return 0
		fi
		sleep 2
	done
	log "Nexus REST not reachable at ${NEXUS_REST}/v1/status after 4 minutes"
	return 1
}

# Resolve the admin password to use for REST calls. Two cases:
#  1. Already bootstrapped (BOOTSTRAP_DONE_FILE exists): use
#     INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD directly.
#  2. First bootstrap: log in with the well-known default `admin123`
#     (compose.yml pins NEXUS_SECURITY_RANDOMPASSWORD=false), rotate to
#     the operator's password, mark done.
rotate_admin_password() {
	ADMIN_USER="admin"
	if docker exec "${PKGCACHE_CONTAINER}" test -f "${BOOTSTRAP_DONE_FILE}"; then
		log "Already bootstrapped; using stored admin password"
		ADMIN_PASS="${INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD}"
		return 0
	fi

	log "Rotating admin password from default '${NEXUS_DEFAULT_PASSWORD}'"
	if ! nexus_curl -fsS -u "admin:${NEXUS_DEFAULT_PASSWORD}" \
		-H "Content-Type: text/plain" \
		-X PUT "${NEXUS_REST}/v1/security/users/admin/change-password" \
		--data-binary "${INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD}"; then
		# Default password may already have been rotated by a previous
		# (partially-completed) bootstrap. Probe with the configured
		# password before giving up.
		if nexus_curl -fsS -o /dev/null -u "admin:${INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD}" \
			"${NEXUS_REST}/v1/repositories" >/dev/null 2>&1; then
			log "Default rotation rejected but configured password authenticates; assuming previous bootstrap, marking done"
		else
			log "Cannot authenticate with default '${NEXUS_DEFAULT_PASSWORD}' nor with configured INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD."
			log "Wipe ${INFINITO_PACKAGE_CACHE_HOST_PATH} (e.g. via 'make cache-clean') and retry."
			return 1
		fi
	fi
	docker exec "${PKGCACHE_CONTAINER}" touch "${BOOTSTRAP_DONE_FILE}"
	ADMIN_PASS="${INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD}"
}

# Ensure a single named blobstore "default" with quota equal to
# INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX. POST returns 201 on create,
# 400/409 if the name is taken; both are acceptable.
ensure_blobstore() {
	# Quota expects MB integer; convert from "Ng".
	local quota_gb="${INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX%g}"
	local quota_mb=$((quota_gb * 1024))
	local payload
	payload="$(printf '{"name":"default","path":"default","softQuota":{"type":"spaceUsedQuota","limit":%d}}' "${quota_mb}")"
	local code
	code="$(nexus_curl -sS -o /dev/null -w '%{http_code}' \
		-u "${ADMIN_USER}:${ADMIN_PASS}" \
		-H "Content-Type: application/json" \
		-X POST "${NEXUS_REST}/v1/blobstores/file" \
		--data "${payload}" || true)"
	case "${code}" in
	201 | 204) log "blobstore default created (HTTP ${code})" ;;
	400 | 409) log "blobstore default already exists (HTTP ${code})" ;;
	*)
		log "unexpected HTTP ${code} creating blobstore"
		return 1
		;;
	esac
}

# Create one proxy repo. The Nexus REST API differs slightly per
# format, so we accept the per-format payload from the caller.
ensure_proxy_repo() {
	local format="$1" name="$2" payload="$3"
	local code
	code="$(nexus_curl -sS -o /dev/null -w '%{http_code}' \
		-u "${ADMIN_USER}:${ADMIN_PASS}" \
		-H "Content-Type: application/json" \
		-X POST "${NEXUS_REST}/v1/repositories/${format}/proxy" \
		--data "${payload}" || true)"
	case "${code}" in
	201 | 204) log "${format} proxy ${name} created (HTTP ${code})" ;;
	400 | 409) log "${format} proxy ${name} already exists (HTTP ${code})" ;;
	*)
		log "unexpected HTTP ${code} creating ${format} proxy ${name}"
		return 1
		;;
	esac
}

ensure_all_proxies() {
	local storage='"storage":{"blobStoreName":"default","strictContentTypeValidation":true},"proxy":{"contentMaxAge":1440,"metadataMaxAge":1440},"negativeCache":{"enabled":true,"timeToLive":1440},"httpClient":{"blocked":false,"autoBlock":true}'

	# apt-debian. Distribution required for apt format.
	ensure_proxy_repo apt apt-debian "$(printf '{"name":"apt-debian","online":true,%s,"proxy":{"remoteUrl":"http://deb.debian.org/debian","contentMaxAge":1440,"metadataMaxAge":1440},"apt":{"distribution":"bookworm","flat":false}}' "${storage}")"
	# apt-ubuntu.
	ensure_proxy_repo apt apt-ubuntu "$(printf '{"name":"apt-ubuntu","online":true,%s,"proxy":{"remoteUrl":"http://archive.ubuntu.com/ubuntu","contentMaxAge":1440,"metadataMaxAge":1440},"apt":{"distribution":"jammy","flat":false}}' "${storage}")"
	# pypi.
	ensure_proxy_repo pypi pypi-proxy "$(printf '{"name":"pypi-proxy","online":true,%s,"proxy":{"remoteUrl":"https://pypi.org/","contentMaxAge":1440,"metadataMaxAge":1440}}' "${storage}")"
	# npm.
	ensure_proxy_repo npm npm-proxy "$(printf '{"name":"npm-proxy","online":true,%s,"proxy":{"remoteUrl":"https://registry.npmjs.org/","contentMaxAge":1440,"metadataMaxAge":1440}}' "${storage}")"
	# helm-bitnami. Registered for future helm-driven roles; no client
	# wiring today since no role pulls helm charts.
	ensure_proxy_repo helm helm-bitnami "$(printf '{"name":"helm-bitnami","online":true,%s,"proxy":{"remoteUrl":"https://charts.bitnami.com/bitnami","contentMaxAge":1440,"metadataMaxAge":1440}}' "${storage}")"
	# raw-githubusercontent.
	ensure_proxy_repo raw raw-githubusercontent "$(printf '{"name":"raw-githubusercontent","online":true,%s,"proxy":{"remoteUrl":"https://raw.githubusercontent.com/","contentMaxAge":1440,"metadataMaxAge":1440},"raw":{"contentDisposition":"ATTACHMENT"}}' "${storage}")"
}

# Accept the Sonatype Nexus Repository - Community Edition EULA. Since
# 3.71+ the CE build refuses to serve cached artifacts (HTTP 403 with a
# `You must accept the End User License Agreement` body) until the EULA
# flag is flipped via REST. The simple index (and other metadata) is
# unaffected, so the symptom is "pip resolves but every .whl GET 403s".
# Repeated POSTs are accepted (204) once the flag is true.
ensure_eula_accepted() {
	local code
	# Sonatype rejects (HTTP 500) any payload whose `disclaimer` field is
	# not byte-identical to the canonical text — including the curly
	# unicode single quotes around `accepted:false` / `accepted:true`.
	# Hence the SC1112 suppression: the unicode quotes are intentional.
	# shellcheck disable=SC1112
	code="$(nexus_curl -sS -o /dev/null -w '%{http_code}' \
		-u "${ADMIN_USER}:${ADMIN_PASS}" \
		-H "Content-Type: application/json" \
		-X POST "${NEXUS_REST}/v1/system/eula" \
		--data '{"accepted":true,"disclaimer":"Use of Sonatype Nexus Repository - Community Edition is governed by the End User License Agreement at https://links.sonatype.com/products/nxrm/ce-eula. By returning the value from ‘accepted:false’ to ‘accepted:true’, you acknowledge that you have read and agree to the End User License Agreement at https://links.sonatype.com/products/nxrm/ce-eula."}' || true)"
	case "${code}" in
	200 | 204) log "EULA accepted (HTTP ${code})" ;;
	*)
		log "unexpected HTTP ${code} accepting EULA"
		return 1
		;;
	esac
}

# Enable anonymous read access globally so client tools (pip, npm,
# apt, helm) can hit /repository/<name>/... without credentials baked
# into pip.conf / .npmrc / sources.list. Nexus 3 ships with anonymous
# disabled; without this PUT every proxy GET returns 401 and pip
# prompts for a password (EOFError under non-interactive use).
ensure_anonymous_access() {
	local code
	code="$(nexus_curl -sS -o /dev/null -w '%{http_code}' \
		-u "${ADMIN_USER}:${ADMIN_PASS}" \
		-H "Content-Type: application/json" \
		-X PUT "${NEXUS_REST}/v1/security/anonymous" \
		--data '{"enabled":true,"userId":"anonymous","realmName":"NexusAuthorizingRealm"}' || true)"
	case "${code}" in
	200 | 204) log "anonymous access enabled (HTTP ${code})" ;;
	*)
		log "unexpected HTTP ${code} enabling anonymous access"
		return 1
		;;
	esac
}

main() {
	wait_for_nexus
	rotate_admin_password
	ensure_eula_accepted
	ensure_anonymous_access
	ensure_blobstore
	ensure_all_proxies
	log "bootstrap done"
}

main "$@"
