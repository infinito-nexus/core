#!/usr/bin/env bash
# Deploy a compose role against the booted server by replaying the
# Production block of its README inside the CI container.
# Env: GUIDE_ROLE.
set -euo pipefail

awk '/^### Production$/{p=1} p && /^```bash$/{c=1; next} c && /^```$/{exit} c' \
	"roles/${GUIDE_ROLE}/README.md" >/tmp/deploy.sh
sed -n '1,/docker run/p' /tmp/deploy.sh | grep -E '^[A-Z_]+=' |
	sed 's#^HOST=.*#HOST=localhost#' >/tmp/run.sh
perl -0777 -ne "print \$1 if /bash -c '(.*)'/s" /tmp/deploy.sh >>/tmp/run.sh
test -s /tmp/run.sh
sed -i "s#<your-ssh-public-key>#ssh-ed25519 AAAA_TEST_DUMMY_KEY github-ci-dummy@infinito#" /tmp/run.sh
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh
docker exec -i "${INFINITO_CONTAINER}" bash -s </tmp/run.sh
