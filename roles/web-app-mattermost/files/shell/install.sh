#!/usr/bin/env bash
# Param: $1 - Mattermost release version without the leading v, e.g. 11.11.0
set -euo pipefail

version="${1:?Mattermost release version required}"
arch="$(dpkg --print-architecture)"
plugins_dir=/mattermost/prepackaged_plugins

groupadd --gid 2000 mattermost
useradd --uid 2000 --gid 2000 --comment "" --home-dir /mattermost mattermost

curl -fsSL --retry 3 --retry-all-errors --retry-delay 2 --connect-timeout 30 --max-time 900 \
	"https://releases.mattermost.com/${version}/mattermost-team-${version}-linux-${arch}.tar.gz" |
	tar -xz -C /

if [[ ! -d "${plugins_dir}" ]]; then
	listed="$(
		curl -fsSL --retry 3 --retry-all-errors --retry-delay 2 --connect-timeout 30 --max-time 300 \
			"https://raw.githubusercontent.com/mattermost/mattermost/v${version}/server/Makefile" |
			sed -n -E 's/^PLUGIN_PACKAGES \+= (mattermost-plugin-[^ ]+)$/\1/p'
	)"
	if [[ -z "${listed}" ]]; then
		echo "server/Makefile of v${version} lists no prepackaged plugins" >&2
		exit 1
	fi
	mkdir "${plugins_dir}"
	while read -r plugin; do
		for file in "${plugin}-linux-${arch}.tar.gz" "${plugin}-linux-${arch}.tar.gz.sig"; do
			curl -fsSL --retry 3 --retry-all-errors --retry-delay 2 --connect-timeout 30 --max-time 900 -o "${plugins_dir}/${file}" \
				"https://plugins.releases.mattermost.com/release/${file}"
		done
	done <<<"${listed}"
fi

mkdir -p /mattermost/data /mattermost/logs /mattermost/plugins /mattermost/client/plugins /mattermost/.postgresql
chmod 700 /mattermost/.postgresql
chown -R mattermost:mattermost /mattermost
