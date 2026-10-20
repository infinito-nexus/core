#!/usr/bin/env bash
# Install the runtime of the NLLB-200 inference server. Every input is a
# Dockerfile ARG, which docker exposes to this RUN as an environment variable.
#
# Param: NLLB_GPU  'true' when the deploy resolved a usable GPU
set -euo pipefail

TORCH_VERSION=2.9.1
TRANSFORMERS_VERSION=4.57.1
SENTENCEPIECE_VERSION=0.2.1
FASTAPI_VERSION=0.122.0
UVICORN_VERSION=0.40.0

if [ "${NLLB_GPU}" = "true" ]; then
	pip install --no-cache-dir "torch==${TORCH_VERSION}"
else
	pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==${TORCH_VERSION}"
fi

pip install --no-cache-dir \
	"transformers==${TRANSFORMERS_VERSION}" \
	"sentencepiece==${SENTENCEPIECE_VERSION}" \
	"fastapi==${FASTAPI_VERSION}" \
	"uvicorn[standard]==${UVICORN_VERSION}"
