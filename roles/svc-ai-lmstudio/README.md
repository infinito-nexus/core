# LM Studio

## Description

[LM Studio](https://lmstudio.ai/) is a runtime for open large language models. Its headless server mode loads models from a local store and answers chat and completion requests over an OpenAI-compatible HTTP API, so prompts and model weights stay on the machine that runs them.

## Overview

This role deploys LM Studio as a headless model server in a single container, in both Docker Compose and Docker Swarm deployments. The server listens on port 1234 on the internal container network and is not published through the reverse proxy, while downloaded models and server settings persist in a dedicated volume. The role downloads its declared models at deploy time and the LiteLLM Gateway publishes them under the same aliases Ollama uses, so a consumer asks for one model name and reaches whichever backend the deployment provides.

## Features

- **OpenAI-compatible endpoint:** The headless server answers `/v1` requests on port 1234 inside the container network.
- **CPU inference:** The role builds its own image from the pinned llmster release for the host's architecture, amd64 or arm64, keeps only the CPU llama.cpp engine and passes no GPU device into the container.
- **Persistent model store:** A named volume mounted at `/root/.lmstudio` keeps downloaded models and server settings across redeploys.
- **Preloaded models:** Every entry of `services.lmstudio.preload_models` is a file of the [svc-ai-models](../svc-ai-models/README.md) store, which the role mounts read-only. The role refuses to start while the store lacks one, and links `<models>/<repo>/<file>` to the store file instead of downloading a copy, so a host that also runs Ollama holds the file once. Each entry carries the `repo` and `file` LM Studio indexes it under, the `name` the gateway addresses it by and the `alias` the gateway publishes it as.
- **Loading:** The link loads nothing. LM Studio serves with just-in-time loading, so the first `/v1/chat/completions` naming a `name` loads that model; the gateway's warm task issues that first request at deploy time.
- **Gateway backend:** The LiteLLM Gateway publishes those aliases, which are the names Ollama serves too, so the same model name routes to whichever local backend a deployment runs.
- **Bounded resources:** The container is capped at 4 CPUs, 8 GB of memory and 2048 processes, and the role declares a minimum of 4 GB free storage for building the image; downloaded models grow the volume beyond that.
- **Backup integration:** Backup Docker Volumes snapshots the model volume when that role is present, without stopping the container.
