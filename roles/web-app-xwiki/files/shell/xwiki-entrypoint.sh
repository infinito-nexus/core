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

if [ -f /etc/infinito/xwiki.properties ]; then
	mkdir -p /usr/local/xwiki/data
	cp /etc/infinito/xwiki.properties /usr/local/xwiki/data/xwiki.properties
fi

if [ -n "${XWIKI_SUPERADMIN_PASSWORD:-}" ]; then
	for cfg in /usr/local/xwiki/data/xwiki.cfg \
		"/usr/local/tomcat/webapps/${CONTEXT_PATH:-ROOT}/WEB-INF/xwiki.cfg"; do
		[ -f "${cfg}" ] || continue
		sed -i -E '/^#? ?xwiki\.superadmin(password)? ?=/d' "${cfg}"
		printf '%s\n' \
			'xwiki.superadmin=1' \
			"xwiki.superadminpassword=${XWIKI_SUPERADMIN_PASSWORD}" \
			>>"${cfg}"
	done
fi

exec docker-entrypoint.sh "$@"
