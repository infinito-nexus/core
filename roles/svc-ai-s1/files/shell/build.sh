#!/usr/bin/env bash
# Build the System One server for one flavor. Every input is a Dockerfile ARG,
# which docker exposes to this RUN as an environment variable.
#
# Param: S1_FLAVOR            laya | torch | onnx
# Param: S1_GPU               'true' when the deploy resolved a usable GPU
# Param: S1_LAYA_CHECKPOINTS  comma list of HuggingFace repo ids (laya only)
# Param: S1_JEFF_REPOSITORY   git url of the jeff server (torch, onnx)
# Param: S1_JEFF_REF          commit the jeff install is pinned to
# Param: S1_JEFF_MODEL_REPO   HuggingFace repo id of the jeff checkpoint
# Param: S1_JEFF_MODEL_PATH   where that checkpoint lands in the image
set -euo pipefail

rm -rf /var/lib/apt/lists/*
apt-get -o Acquire::Retries=3 update
apt-get -o Acquire::Retries=3 install -y --no-install-recommends git
rm -rf /var/lib/apt/lists/*

if [ "${S1_GPU}" = "true" ]; then
	pip install --no-cache-dir torch
	laya_extras="serve,fast"
else
	pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch
	laya_extras="serve"
fi

if [ "${S1_FLAVOR}" = "laya" ]; then
	pip install --no-cache-dir "laya[${laya_extras}]" huggingface_hub
	IFS=',' read -ra checkpoints <<<"${S1_LAYA_CHECKPOINTS}"
	for checkpoint in "${checkpoints[@]}"; do
		hf download "${checkpoint}"
	done
	exit 0
fi

extra=""
if [ "${S1_FLAVOR}" = "onnx" ]; then
	extra="[onnx]"
fi

pip install --no-cache-dir "jeff${extra} @ git+${S1_JEFF_REPOSITORY}@${S1_JEFF_REF}" huggingface_hub
hf download "${S1_JEFF_MODEL_REPO}" --local-dir "${S1_JEFF_MODEL_PATH}"

if [ "${S1_FLAVOR}" = "onnx" ]; then
	python -c "from jeff.backends.onnx_export import export_encoder; export_encoder('${S1_JEFF_MODEL_PATH}', int8=True)"
fi
