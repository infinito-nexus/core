#!/usr/bin/env bash
# shellcheck shell=bash
# nocheck: raw-docker  this runs on the developer's host to bring the dev cache up, where the `container` wrapper is not on PATH (verified: `which container` -> not found)
# Idempotent Nexus 3 OSS proxy bootstrap.
# See docs/contributing/environment/cache.md.

set -euo pipefail

: "${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_MAX_AGE_MIN:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_METADATA_MAX_AGE_MIN:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_UPSTREAMS:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_CONTAINER:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_PORT:?Source scripts/meta/env/load.sh first}"

CACHE_CONTENT_MAX_AGE_MIN="${INFINITO_CACHE_PACKAGE_MAX_AGE_MIN}"
CACHE_METADATA_MAX_AGE_MIN="${INFINITO_CACHE_PACKAGE_METADATA_MAX_AGE_MIN}"

PKGCACHE_CONTAINER="${INFINITO_CACHE_PACKAGE_CONTAINER}"
NEXUS_REST="http://127.0.0.1:${INFINITO_CACHE_PACKAGE_PORT}/service/rest"

BOOTSTRAP_DONE_FILE="/nexus-data/.infinito-bootstrap-done"
NEXUS_ADMIN_PW_FILE="/nexus-data/.infinito-admin-password"
NEXUS_DEFAULT_PASSWORD="admin123"

log() { printf '[package-cache-bootstrap] %s\n' "$*" >&2; }

nexus_curl() { docker exec "${PKGCACHE_CONTAINER}" curl "$@"; }

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

store_admin_password() {
	printf %s "${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}" |
		docker exec -i "${PKGCACHE_CONTAINER}" sh -c "umask 077; cat > '${NEXUS_ADMIN_PW_FILE}'"
}

rotate_admin_password() {
	ADMIN_USER="admin"
	if docker exec "${PKGCACHE_CONTAINER}" test -f "${BOOTSTRAP_DONE_FILE}"; then
		log "Already bootstrapped; using stored admin password"
		ADMIN_PASS="$(docker exec "${PKGCACHE_CONTAINER}" cat "${NEXUS_ADMIN_PW_FILE}" 2>/dev/null || true)"
		if [ -z "${ADMIN_PASS}" ]; then
			ADMIN_PASS="${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}"
		fi
		return 0
	fi

	log "Rotating admin password from default '${NEXUS_DEFAULT_PASSWORD}'"
	if ! nexus_curl -fsS -u "admin:${NEXUS_DEFAULT_PASSWORD}" \
		-H "Content-Type: text/plain" \
		-X PUT "${NEXUS_REST}/v1/security/users/admin/change-password" \
		--data-binary "${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}"; then
		if nexus_curl -fsS -o /dev/null -u "admin:${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}" \
			"${NEXUS_REST}/v1/repositories" >/dev/null 2>&1; then
			log "Default rotation rejected but configured password authenticates; assuming previous bootstrap, marking done"
		else
			log "Cannot authenticate with default '${NEXUS_DEFAULT_PASSWORD}' nor with configured INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD."
			log "Wipe the Nexus data and retry; the dev stack keeps it under ${INFINITO_CACHE_PACKAGE_HOST_PATH:-} and the role in the package_cache_data volume."
			return 1
		fi
	fi
	store_admin_password
	docker exec "${PKGCACHE_CONTAINER}" touch "${BOOTSTRAP_DONE_FILE}"
	ADMIN_PASS="${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}"
}

ensure_blobstore() {
	local quota_gb="${INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX%g}"
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

ensure_repo() {
	local format="$1" kind="$2" name="$3" payload="$4"
	local code
	code="$(nexus_curl -sS -o /dev/null -w '%{http_code}' \
		-u "${ADMIN_USER}:${ADMIN_PASS}" \
		-H "Content-Type: application/json" \
		-X POST "${NEXUS_REST}/v1/repositories/${format}/${kind}" \
		--data "${payload}" || true)"
	case "${code}" in
	201 | 204) log "${format} ${kind} ${name} created (HTTP ${code})" ;;
	400 | 409)
		code="$(nexus_curl -sS -o /dev/null -w '%{http_code}' \
			-u "${ADMIN_USER}:${ADMIN_PASS}" \
			-H "Content-Type: application/json" \
			-X PUT "${NEXUS_REST}/v1/repositories/${format}/${kind}/${name}" \
			--data "${payload}" || true)"
		case "${code}" in
		200 | 204) log "${format} ${kind} ${name} updated (HTTP ${code})" ;;
		*)
			log "unexpected HTTP ${code} updating ${format} ${kind} ${name}"
			return 1
			;;
		esac
		;;
	*)
		log "unexpected HTTP ${code} creating ${format} ${kind} ${name}"
		return 1
		;;
	esac
}

ensure_proxy_repo() { ensure_repo "$1" proxy "$2" "$3"; }

# autoBlock stays off: once Nexus blocks a remote it answers every client
# with `404 Remote Auto Blocked` for the whole block window, so a single
# upstream hiccup fails every concurrent job instead of just the request
# that hit it.
ensure_all_proxies() {
	local storage='"storage":{"blobStoreName":"default","strictContentTypeValidation":true},"proxy":{"contentMaxAge":'"${CACHE_CONTENT_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_METADATA_MAX_AGE_MIN}"'},"negativeCache":{"enabled":true,"timeToLive":'"${CACHE_METADATA_MAX_AGE_MIN}"'},"httpClient":{"blocked":false,"autoBlock":false}'

	local record name flavor url distribution depth content_max_age content extra

	for record in ${INFINITO_CACHE_UPSTREAMS//,/ }; do
		IFS='|' read -r name flavor url distribution depth content_max_age <<<"${record}"
		content="${content_max_age:-${CACHE_CONTENT_MAX_AGE_MIN}}"
		case "${flavor}" in
		apt) extra=',"apt":{"distribution":"'"${distribution}"'","flat":false}' ;;
		yum) extra=',"yum":{"repodataDepth":'"${depth}"'}' ;;
		raw) extra=',"raw":{"contentDisposition":"ATTACHMENT"}' ;;
		*) extra='' ;;
		esac
		ensure_proxy_repo "${flavor}" "${name}" \
			'{"name":"'"${name}"'","online":true,'"${storage}"',"proxy":{"remoteUrl":"'"${url}"'","contentMaxAge":'"${content}"',"metadataMaxAge":'"${CACHE_METADATA_MAX_AGE_MIN}"'}'"${extra}"'}'
	done
}

ensure_eula_accepted() {
	local code
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
