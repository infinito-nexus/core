#!/bin/bash
set -euo pipefail

MARKER=/var/lib/matrix-mdad/bootstrap.done
SYNAPSE_UNIT=/etc/systemd/system/matrix-synapse.service
mkdir -p /var/lib/matrix-mdad
if [ -f "$MARKER" ] && [ -f "$SYNAPSE_UNIT" ]; then
  echo ">>> matrix-mdad-bootstrap: marker + synapse unit present, skipping"
  exit 0
fi
if [ -f "$MARKER" ] && [ ! -f "$SYNAPSE_UNIT" ]; then
  echo ">>> matrix-mdad-bootstrap: stale marker (no synapse unit), re-running"
  rm -f "$MARKER"
fi

export PATH="/opt/ansible/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

PYTHON=/opt/ansible/bin/python3
ready=0
attempt=0
while [ "$attempt" -lt 30 ]; do
  if "$PYTHON" -c 'import _posixsubprocess, subprocess, ssl, ctypes' >/dev/null 2>&1; then
    ready=1
    break
  fi
  attempt=$((attempt + 1))
  echo ">>> matrix-mdad-bootstrap: python runtime not ready yet (attempt ${attempt}/30), waiting"
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "!!! matrix-mdad-bootstrap: python runtime never became importable, aborting" >&2
  "$PYTHON" -c 'import _posixsubprocess' || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  exit 1
fi

cd /mdad

GALAXY_STAMP=roles/galaxy/.requirements.sha256
GALAXY_WANT=$(sha256sum requirements.yml | cut -d' ' -f1)
if [ -f "$GALAXY_STAMP" ] && [ "$(cat "$GALAXY_STAMP")" = "$GALAXY_WANT" ] && [ -d roles/galaxy ]; then
  echo ">>> matrix-mdad-bootstrap: galaxy roles match requirements.yml ($GALAXY_WANT), skipping install"
else
  START_GALAXY=$SECONDS
  echo ">>> matrix-mdad-bootstrap: starting ansible-galaxy install"
  rm -f "$GALAXY_STAMP"
  /opt/ansible/bin/ansible-galaxy install -r requirements.yml -p roles/galaxy/ --force
  printf '%s\n' "$GALAXY_WANT" > "$GALAXY_STAMP"
  echo "<<< matrix-mdad-bootstrap: galaxy install done in $((SECONDS - START_GALAXY))s"
fi

START_PLAY=$SECONDS
echo ">>> matrix-mdad-bootstrap: starting ansible-playbook setup.yml --tags=${MATRIX_MDAD_PLAYBOOK_TAGS:-setup-all,start}"
/opt/ansible/bin/ansible-playbook -i inventory/hosts setup.yml --tags="${MATRIX_MDAD_PLAYBOOK_TAGS:-setup-all,start}"
echo "<<< matrix-mdad-bootstrap: playbook done in $((SECONDS - START_PLAY))s"

touch "$MARKER"
echo ">>> matrix-mdad-bootstrap: marker written, total $SECONDS s"
