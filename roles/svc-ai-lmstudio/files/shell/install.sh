#!/usr/bin/env bash
# Param: $1 - llmster release, e.g. 0.0.25-1
set -euo pipefail

version="${1:?llmster release required}"
case "$(uname -m)" in
x86_64) platform=linux-x64 ;;
aarch64) platform=linux-arm64 ;;
*)
	echo "LM Studio publishes no llmster build for $(uname -m)" >&2
	exit 1
	;;
esac
release="https://llmster.lmstudio.ai/download/${version}-${platform}.full"
backends=/app/.bundle/bin/extensions/backends

curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 10 --max-time 3600 -o /tmp/llmster.tar.gz "${release}.tar.gz"
curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 10 --max-time 60 -o /tmp/llmster.sha512 "${release}.sha512"
echo "$(</tmp/llmster.sha512)  /tmp/llmster.tar.gz" | sha512sum -c -
tar -xzf /tmp/llmster.tar.gz -C /app
rm -rf /tmp/llmster.tar.gz /tmp/llmster.sha512 \
	/app/.bundle/bin/extensions/frameworks \
	"${backends}"/vendor/* \
	"${backends}"/*-nvidia-* \
	"${backends}"/*-vulkan-*
if ! compgen -G "${backends}/llama.cpp-*" >/dev/null; then
	echo "the llmster ${version} ${platform} release ships no llama.cpp engine" >&2
	exit 1
fi
test -x /app/llmster
test -x /app/.bundle/lms
