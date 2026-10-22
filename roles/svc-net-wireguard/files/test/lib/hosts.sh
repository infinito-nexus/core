#!/usr/bin/env bash
# shellcheck shell=bash
#
# Expects from test.sh: COMPOSE_FILE, PREFIX, NETWORK, HOST_I, HOST_II,
# HOST_III and HOSTS.

hosts_compose() {
	HOST_I="${HOST_I}" HOST_II="${HOST_II}" HOST_III="${HOST_III}" NETWORK="${NETWORK}" \
		container compose --file "${COMPOSE_FILE}" --project-name "${PREFIX}" "$@"
}

on() {
	local host="$1"
	shift
	container exec "${host}" "$@"
}

provision_host() {
	local host="$1"
	on "${host}" sh -c 'rm -rf /var/lib/apt/lists/* \
		&& apt-get -o Acquire::Retries=3 update -qq \
		&& apt-get -o Acquire::Retries=3 install -y -qq --no-install-recommends \
			python3 openssh-server \
		&& mkdir -p /run/sshd /root/.ssh \
		&& chmod 700 /root/.ssh \
		&& ssh-keygen -q -t ed25519 -N "" -f /root/.ssh/id_ed25519 \
		&& /usr/sbin/sshd' >/dev/null
}

authorize_every_host() {
	local host keys=""
	for host in "${HOSTS[@]}"; do
		keys+="$(on "${host}" cat /root/.ssh/id_ed25519.pub)"$'\n'
	done
	for host in "${HOSTS[@]}"; do
		printf '%s' "${keys}" | container exec -i "${host}" \
			sh -c 'cat >/root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys'
	done
}
