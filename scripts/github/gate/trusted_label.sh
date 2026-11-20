#!/usr/bin/env bash
#
# Inputs via env:
#   TRUSTED    "true" when the fork PR carries the maintainer '🛡️ Trusted' label.
#   PR_NUMBER  the pull request number, named in the refusal.

set -euo pipefail

: "${TRUSTED:?}"
: "${PR_NUMBER:?}"

if [[ "${TRUSTED}" != "true" ]]; then
	echo "Fork PR #${PR_NUMBER} is not labelled '🛡️ Trusted'. The privileged image build and mirror run fork content with a packages:write token, so they start only after a maintainer reviewed the head and applied the label." >&2
	exit 1
fi
echo "Fork PR #${PR_NUMBER} carries '🛡️ Trusted'; the privileged image build and mirror may run."
