#!/usr/bin/env bash
#
# XWiki-specific rescue diagnostics: probe what the generic snapshot cannot,
# namely whether the extension repositories (nexus.xwiki.org, Maven Central)
# are reachable from the container, plus the mounted xwiki.properties. Writes
# into the shared rescue diagnostics folder so it ships in the uploaded
# snapshot. Prints one summary line and always exits 0 so the final rescue.sh
# still runs.
#
# Required environment:
#   XWIKI_CONTAINER_ADDRESS   exec address of the xwiki container
set -u

: "${XWIKI_CONTAINER_ADDRESS:?XWIKI_CONTAINER_ADDRESS not set}"

OUT_BASE="${INFINITO_RESCUE_DIAGNOSTICS_DIR:?INFINITO_RESCUE_DIAGNOSTICS_DIR not set (SPOT: group_vars/all/05_paths.yml)}"
mkdir -p "${OUT_BASE}"
out="${OUT_BASE}/xwiki-extensions.txt"

runtime() {
	if command -v container >/dev/null 2>&1; then
		container "$@"
	else
		docker "$@"
	fi
}

{
	echo "===== extension repo reachability ====="
	runtime exec "${XWIKI_CONTAINER_ADDRESS}" sh -lc '
		echo "== DNS ==";
		getent hosts nexus.xwiki.org || true;  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
		getent hosts repo1.maven.org || true;  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
		echo "== HTTP ==";
		wget -S -O- -T 10 https://nexus.xwiki.org/ 2>&1 | head -n 30 || true;  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
		wget -S -O- -T 10 https://repo1.maven.org/maven2/ 2>&1 | head -n 30 || true;  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
	' 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
	echo
	echo "===== xwiki.properties (first 200 lines) ====="
	# shellcheck disable=SC2016  # $p expands in the inner sh -lc, not here
	runtime exec "${XWIKI_CONTAINER_ADDRESS}" sh -lc '
		p=/usr/local/tomcat/webapps/ROOT/WEB-INF/xwiki.properties;
		ls -la "$p" || true;  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
		sed -n "1,200p" "$p" 2>/dev/null || true;  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
		echo "== extension.repositories ==";
		grep -n "^[[:space:]]*extension\.repositories" "$p" 2>/dev/null || true;  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
	' 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
} >"${out}" 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

echo "🩺 XWiki extension diagnostics captured to ${out}"
exit 0
