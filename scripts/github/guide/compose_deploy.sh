#!/usr/bin/env bash
# Render the role's "### Production" bash block and replay it against the
# running compose server, exactly as the guide instructs a human to.
# Env: GUIDE_ROLE; INFINITO_CONTAINER comes from scripts/meta/env/load.sh.
set -euo pipefail

: "${GUIDE_ROLE:?}"

python3 -m cli.build.docs.readme.production "${GUIDE_ROLE}" >/tmp/deploy.sh
sed -n '1,/docker run/p' /tmp/deploy.sh | grep -E '^[A-Z_]+=' |
	sed 's#^HOST=.*#HOST=localhost#' >/tmp/run.sh
perl -0777 -ne "print \$1 if /bash -c '(.*)'/s" /tmp/deploy.sh >>/tmp/run.sh
test -s /tmp/run.sh
# shellcheck source=/dev/null
source scripts/meta/env/load.sh
sed -i "s#<your-ssh-public-key>#ssh-ed25519 AAAA_TEST_DUMMY_KEY github-ci-dummy@infinito#" /tmp/run.sh
sed -i "s#<your-domain>#${INFINITO_DOMAIN}#" /tmp/run.sh
sed -i "s#<your-clearnet-resolver>#${INFINITO_DNS_IP}#" /tmp/run.sh
docker exec -i "${INFINITO_CONTAINER}" bash -s </tmp/run.sh
