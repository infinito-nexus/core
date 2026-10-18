#!/bin/sh
#
# The stock entrypoint restores WEB-INF/xwiki.properties from the data volume and
# then rewrites it in place; a read-only mount over WEB-INF (the swarm config
# object) makes that writeback fail. Feed our config through the data volume and
# let the stock entrypoint own WEB-INF.
#
# The superadmin credential is written here rather than baked by the Dockerfile:
# a rotation rebuilds the image on the manager, but `docker stack deploy
# --resolve-image never` leaves the mutable tag alone, so a worker that already
# holds it keeps serving the pre-rotation password and answers 401 to every
# authenticated call the deploy makes afterwards.
#
# Both copies are written because the stock entrypoint's other_starts() runs
# `restoreConfigurationFile 'xwiki.cfg'`, which copies the data volume over
# WEB-INF on every start but the first. Writing only WEB-INF would survive the
# first boot and be reverted by the second.
#
# The keys are deleted and re-appended rather than substituted: the stock
# xwiki_replace matches `#? ?key ?=`, so a commented or spaced default has to go
# too, and a generated password must never reach a sed replacement, where its
# delimiter or backreference characters would be read as syntax.
set -e

: "${XWIKI_PROPERTIES_SOURCE:?set from meta/volumes.yml by the compose environment}"

XWIKI_CFG_NAME=xwiki.cfg
XWIKI_DATA_DIR=/usr/local/xwiki/data
XWIKI_WEBINF_DIR="/usr/local/tomcat/webapps/${CONTEXT_PATH:-ROOT}/WEB-INF"

XWIKI_DATA_CFG="${XWIKI_DATA_DIR}/${XWIKI_CFG_NAME}"
XWIKI_WEBINF_CFG="${XWIKI_WEBINF_DIR}/${XWIKI_CFG_NAME}"

if [ -f "${XWIKI_PROPERTIES_SOURCE}" ]; then
	mkdir -p "${XWIKI_DATA_DIR}"
	cp "${XWIKI_PROPERTIES_SOURCE}" "${XWIKI_DATA_DIR}/$(basename "${XWIKI_PROPERTIES_SOURCE}")"
fi

if [ -n "${XWIKI_SUPERADMIN_PASSWORD:-}" ]; then
	for cfg in "${XWIKI_DATA_CFG}" "${XWIKI_WEBINF_CFG}"; do
		[ -f "${cfg}" ] || continue
		sed -i -E '/^#? ?xwiki\.superadmin(password)? ?=/d' "${cfg}"
		printf '%s\n' \
			'xwiki.superadmin=1' \
			"xwiki.superadminpassword=${XWIKI_SUPERADMIN_PASSWORD}" \
			>>"${cfg}"
	done
fi

if [ -n "${XWIKI_CFG_LDAP_SERVER:-}" ]; then
	for cfg in "${XWIKI_DATA_CFG}" "${XWIKI_WEBINF_CFG}"; do
		[ -f "${cfg}" ] || continue
		sed -i -E '/^#? ?xwiki\.authentication\.ldap\./d' "${cfg}"
		printf '%s\n' \
			"xwiki.authentication.ldap.server=${XWIKI_CFG_LDAP_SERVER}" \
			"xwiki.authentication.ldap.port=${XWIKI_CFG_LDAP_PORT}" \
			"xwiki.authentication.ldap.base_DN=${XWIKI_CFG_LDAP_BASE_DN}" \
			"xwiki.authentication.ldap.bind_DN=${XWIKI_CFG_LDAP_BIND_DN}" \
			"xwiki.authentication.ldap.bind_pass=${XWIKI_CFG_LDAP_BIND_PASS}" \
			"xwiki.authentication.ldap.fields_mapping=${XWIKI_CFG_LDAP_FIELDS_MAPPING}" \
			"xwiki.authentication.ldap.group_mapping=${XWIKI_CFG_LDAP_GROUP_MAPPING}" \
			"xwiki.authentication.ldap.mode_group_sync=always" \
			"xwiki.authentication.ldap.trylocal=${XWIKI_CFG_LDAP_TRYLOCAL}" \
			"xwiki.authentication.ldap.update_user=1" \
			>>"${cfg}"
	done
fi

exec docker-entrypoint.sh "$@"
