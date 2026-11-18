#!/usr/bin/env bash
# Install the runtime of the NLLB-200 inference server. Every input is a
# Dockerfile ARG, which docker exposes to this RUN as an environment variable.
#
# Param: NLLB_GPU       'true' when the deploy resolved a usable GPU
# Param: TORCH_VERSION  the torch release every AI image installs (AI_TORCH_VERSION)
set -euo pipefail

TORCH="torch==${TORCH_VERSION:?TORCH_VERSION is the build arg AI_TORCH_VERSION}"
TRANSFORMERS_VERSION=4.57.1
SENTENCEPIECE_VERSION=0.2.1
FASTAPI_VERSION=0.122.0
UVICORN_VERSION=0.40.0

if [ "${NLLB_GPU}" = "true" ]; then
	pip install --no-cache-dir "${TORCH}"
else
	pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "${TORCH}"
fi

pip install --no-cache-dir \
	"transformers==${TRANSFORMERS_VERSION}" \
	"sentencepiece==${SENTENCEPIECE_VERSION}" \
	"fastapi==${FASTAPI_VERSION}" \
	"uvicorn[standard]==${UVICORN_VERSION}"
