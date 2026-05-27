#!/usr/bin/env bash
# shellcheck shell=bash
# Idempotent Nexus 3 OSS proxy bootstrap.
# See docs/contributing/environment/cache.md.

set -euo pipefail

: "${INFINITO_CACHE_PACKAGE_HOST_PATH:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_MAX_AGE_MIN:?Source scripts/meta/env/load.sh first}"

CACHE_MAX_AGE_MIN="${INFINITO_CACHE_PACKAGE_MAX_AGE_MIN}"

# REST goes via `docker exec curl` to bypass sandbox network isolation.
PKGCACHE_CONTAINER="infinito-package-cache"
NEXUS_REST="http://127.0.0.1:8081/service/rest"

BOOTSTRAP_DONE_FILE="/nexus-data/.infinito-bootstrap-done"
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

rotate_admin_password() {
	ADMIN_USER="admin"
	if docker exec "${PKGCACHE_CONTAINER}" test -f "${BOOTSTRAP_DONE_FILE}"; then
		log "Already bootstrapped; using stored admin password"
		ADMIN_PASS="${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}"
		return 0
	fi

	log "Rotating admin password from default '${NEXUS_DEFAULT_PASSWORD}'"
	if ! nexus_curl -fsS -u "admin:${NEXUS_DEFAULT_PASSWORD}" \
		-H "Content-Type: text/plain" \
		-X PUT "${NEXUS_REST}/v1/security/users/admin/change-password" \
		--data-binary "${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}"; then
		# Recover from a partially-completed previous bootstrap.
		if nexus_curl -fsS -o /dev/null -u "admin:${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}" \
			"${NEXUS_REST}/v1/repositories" >/dev/null 2>&1; then
			log "Default rotation rejected but configured password authenticates; assuming previous bootstrap, marking done"
		else
			log "Cannot authenticate with default '${NEXUS_DEFAULT_PASSWORD}' nor with configured INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD."
			log "Wipe ${INFINITO_CACHE_PACKAGE_HOST_PATH} (e.g. via 'make clean-cache') and retry."
			return 1
		fi
	fi
	docker exec "${PKGCACHE_CONTAINER}" touch "${BOOTSTRAP_DONE_FILE}"
	ADMIN_PASS="${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}"
}

ensure_blobstore() {
	# Nexus quota expects MB; convert from "Ng".
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
	local storage='"storage":{"blobStoreName":"default","strictContentTypeValidation":true},"proxy":{"contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"negativeCache":{"enabled":true,"timeToLive":'"${CACHE_MAX_AGE_MIN}"'},"httpClient":{"blocked":false,"autoBlock":true}'

	ensure_proxy_repo apt apt-debian "$(printf '{"name":"apt-debian","online":true,%s,"proxy":{"remoteUrl":"http://deb.debian.org/debian","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"apt":{"distribution":"bookworm","flat":false}}' "${storage}")"
	ensure_proxy_repo apt apt-ubuntu "$(printf '{"name":"apt-ubuntu","online":true,%s,"proxy":{"remoteUrl":"http://archive.ubuntu.com/ubuntu","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"apt":{"distribution":"jammy","flat":false}}' "${storage}")"
	ensure_proxy_repo apt apt-debian-security "$(printf '{"name":"apt-debian-security","online":true,%s,"proxy":{"remoteUrl":"http://deb.debian.org/debian-security","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"apt":{"distribution":"bookworm-security","flat":false}}' "${storage}")" # nocheck: url (bare GET on the deb.debian.org redirector returns 404; apt-client paths underneath dists/bookworm-security/ resolve correctly)
	ensure_proxy_repo apt apt-ubuntu-security "$(printf '{"name":"apt-ubuntu-security","online":true,%s,"proxy":{"remoteUrl":"http://security.ubuntu.com/ubuntu","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"apt":{"distribution":"jammy-security","flat":false}}' "${storage}")"
	ensure_proxy_repo pypi pypi-proxy "$(printf '{"name":"pypi-proxy","online":true,%s,"proxy":{"remoteUrl":"https://pypi.org/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'}}' "${storage}")"
	ensure_proxy_repo npm npm-proxy "$(printf '{"name":"npm-proxy","online":true,%s,"proxy":{"remoteUrl":"https://registry.npmjs.org/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'}}' "${storage}")"
	ensure_proxy_repo helm helm-bitnami "$(printf '{"name":"helm-bitnami","online":true,%s,"proxy":{"remoteUrl":"https://charts.bitnami.com/bitnami","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'}}' "${storage}")"
	ensure_proxy_repo raw raw-githubusercontent "$(printf '{"name":"raw-githubusercontent","online":true,%s,"proxy":{"remoteUrl":"https://raw.githubusercontent.com/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"raw":{"contentDisposition":"ATTACHMENT"}}' "${storage}")"
	ensure_proxy_repo raw raw-codeload-github "$(printf '{"name":"raw-codeload-github","online":true,%s,"proxy":{"remoteUrl":"https://codeload.github.com/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"raw":{"contentDisposition":"ATTACHMENT"}}' "${storage}")"
	ensure_proxy_repo rubygems gem-proxy "$(printf '{"name":"gem-proxy","online":true,%s,"proxy":{"remoteUrl":"https://rubygems.org/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'}}' "${storage}")"
	ensure_proxy_repo go go-proxy "$(printf '{"name":"go-proxy","online":true,%s,"proxy":{"remoteUrl":"https://proxy.golang.org/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'}}' "${storage}")"
	ensure_proxy_repo yum yum-rocky "$(printf '{"name":"yum-rocky","online":true,%s,"proxy":{"remoteUrl":"https://download.rockylinux.org/pub/rocky/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"yum":{"repodataDepth":5}}' "${storage}")"
	ensure_proxy_repo yum yum-fedora "$(printf '{"name":"yum-fedora","online":true,%s,"proxy":{"remoteUrl":"https://dl.fedoraproject.org/pub/fedora/linux/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"yum":{"repodataDepth":5}}' "${storage}")"
	ensure_proxy_repo raw raw-packagist "$(printf '{"name":"raw-packagist","online":true,%s,"proxy":{"remoteUrl":"https://repo.packagist.org/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"raw":{"contentDisposition":"ATTACHMENT"}}' "${storage}")" # nocheck: url
	ensure_proxy_repo raw raw-alpine "$(printf '{"name":"raw-alpine","online":true,%s,"proxy":{"remoteUrl":"https://dl-cdn.alpinelinux.org/alpine/","contentMaxAge":'"${CACHE_MAX_AGE_MIN}"',"metadataMaxAge":'"${CACHE_MAX_AGE_MIN}"'},"raw":{"contentDisposition":"ATTACHMENT"}}' "${storage}")"
}

ensure_eula_accepted() {
	local code
	# Sonatype rejects payloads whose disclaimer is not byte-identical;
	# the unicode quotes around accepted:* are intentional.
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
