#!/usr/bin/env bash
#
# Inputs via env (set on the container by parallel.sh):
#   INFINITO_SRC_DIR      repo path baked into the image (from the image ENV).
#   INFINITO_IMAGE        the CI image the inner dev stack should run.
#   INFINITO_PULL_POLICY  compose pull policy for that image.
#   GHCR_USER, GHCR_TOKEN optional creds to pull INFINITO_IMAGE from GHCR.

set -uo pipefail

for _ in $(seq 1 60); do
	state="$(systemctl is-system-running 2>/dev/null || true)"
	case "${state}" in running | degraded) break ;; esac
	sleep 1
done
state="$(systemctl is-system-running 2>/dev/null || true)"
case "${state}" in
running | degraded) ;;
*)
	echo "systemd never reached a running state (last: ${state:-unknown})" >&2
	systemctl --no-pager status 2>/dev/null | head -n 20 >&2 || true
	exit 1
	;;
esac

bash "${INFINITO_SRC_DIR:?}/scripts/tests/dns/install-dockerd.sh"

mkdir -p /etc/docker
printf '{"storage-driver":"fuse-overlayfs","features":{"containerd-snapshotter":false}}\n' >/etc/docker/daemon.json

systemctl enable --now docker

ready=0
for _ in $(seq 1 60); do
	if docker info >/dev/null 2>&1; then
		ready=1
		break
	fi
	sleep 2
done
if [[ "${ready}" -ne 1 ]]; then
	echo "docker daemon never became ready" >&2
	journalctl -u docker --no-pager 2>/dev/null | tail -n 50 >&2 || true
	exit 1
fi

if [[ -n "${GHCR_TOKEN:-}" ]]; then
	echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER:?}" --password-stdin
fi

cd "${INFINITO_SRC_DIR:?}" || exit 1
rm -f .env
make compose-up
exec scripts/tests/dns.sh
