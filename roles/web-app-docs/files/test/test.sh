#!/usr/bin/env bash
# shellcheck shell=bash
#
# Env (templates/test.env.j2):
#   DOCS_TEST_BASE_URL   documentation service on this host
#   DOCS_TEST_DNS        value for the <your-clearnet-resolver> placeholder
#   DOCS_TEST_DOMAIN     value for the <your-domain> placeholder
#   DOCS_TEST_MODE       deployment mode; the instructions describe compose
#   DOCS_TEST_ROLE       role whose page carries the instructions
#   DOCS_TEST_SRC_DIR    repository checkout, mounted into the machine
#   DOCS_TEST_TIMEOUT    seconds to wait for the on-demand build

set -euo pipefail

: "${DOCS_TEST_BASE_URL:?}"
: "${DOCS_TEST_ROLE:?}"
: "${DOCS_TEST_MODE:?}"
: "${DOCS_TEST_TIMEOUT:?}"
: "${DOCS_TEST_DOMAIN:?}"

DUMMY_KEY="ssh-ed25519 AAAA_TEST_DUMMY_KEY docs-guide@infinito"

if [ "${DOCS_TEST_MODE}" != "compose" ]; then
	echo "SKIP: the published instructions describe a compose deployment;"
	echo "      this stack runs ${DOCS_TEST_MODE}."
	exit 0
fi

STAGE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLOCK="${STAGE}/block.sh"

echo "=== Reading the published instructions for ${DOCS_TEST_ROLE} ==="
python3 "${STAGE}/extract.py" "${DOCS_TEST_BASE_URL}" "${DOCS_TEST_ROLE}" \
	--timeout "${DOCS_TEST_TIMEOUT}" >"${BLOCK}"

if [ ! -s "${BLOCK}" ]; then
	echo "ERROR: the page for ${DOCS_TEST_ROLE} shows an empty Production block." >&2
	exit 1
fi

echo "=== Checking they parse as bash ==="
bash -n "${BLOCK}"

sed -i "s#<your-ssh-public-key>#${DUMMY_KEY}#g" "${BLOCK}"
sed -i "s#<your-domain>#${DOCS_TEST_DOMAIN}#g" "${BLOCK}"
sed -i "s#<your-clearnet-resolver>#${DOCS_TEST_DNS:-}#g" "${BLOCK}"
sed -i "s#^HOST=.*#HOST=localhost#" "${BLOCK}"
sed -i "s#--rm -it #--rm #" "${BLOCK}"

if grep -q '<your-' "${BLOCK}"; then
	echo "ERROR: the instructions carry a placeholder this test does not fill:" >&2
	grep -o '<your-[a-z-]*>' "${BLOCK}" | sort -u >&2
	exit 1
fi

bash "${STAGE}/machine.sh" "${BLOCK}"
