#!/usr/bin/env bash
#
# Hand a pre-fetched GGUF to LM Studio, idempotent.
# Runs ON THE HOSTING NODE (delegated); targets the local container via
# `container exec` / `container cp`.
#
# Required env, supplied by the calling Ansible task:
#   LMSTUDIO_LOCAL_CID  resolved container id, local to this node
#   MODEL_FILE          node-side path to the fetched .gguf
#   MODEL_USER_REPO     HuggingFace "user/repo" the file belongs to
#   MODELS_DIR          models folder inside the container, under the
#                       volume target declared in meta/volumes.yml
set -euo pipefail

ADDRESS="${LMSTUDIO_LOCAL_CID:?LMSTUDIO_LOCAL_CID env var (container id) required}"
BASE="$(basename "${MODEL_FILE}")"
TARGET="${MODELS_DIR}/${MODEL_USER_REPO}/${BASE}"

if container exec "$ADDRESS" test -f "${TARGET}"; then
	echo "PRESENT:${BASE}"
	exit 0
fi

if [ ! -f "${MODEL_FILE}" ]; then
	echo "ABSENT:${BASE}"
	exit 0
fi

# nocheck: container-cp - MODEL_FILE is fetched on the node this script runs on
container cp "${MODEL_FILE}" "${ADDRESS}:/tmp/${BASE}"

printf 'y\n' | container exec -i "$ADDRESS" lms import "/tmp/${BASE}" --yes --copy --user-repo "${MODEL_USER_REPO}"
container exec "$ADDRESS" rm -f "/tmp/${BASE}"
echo "IMPORTED:${BASE}"
