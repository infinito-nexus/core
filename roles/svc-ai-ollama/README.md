# Ollama

## Description

[Ollama](https://ollama.com) is a local model server that runs open LLMs on your hardware and exposes a simple HTTP API. Prompts and data stay on your machines, making it the backbone for privacy-first AI.

## Overview

This role deploys Ollama as a local model server using Docker Compose. It integrates with Open WebUI for chat and Flowise for AI workflow automation, and configures local model caching so models can be reused across sessions or run fully offline.

## Features

- **Local model execution:** Run popular open models (chat, code, embeddings) on your own hardware.
- **HTTP API:** Simple, predictable HTTP API for application developers.
- **Local caching:** Models are cached locally to avoid repeated downloads.
- **Pinned model files:** Every entry of `services.ollama.preload_models` names one GGUF file fixed to one commit, with its `sha256` and `bytes`, as `AI_LOCAL_MODELS` in `group_vars/all/16_ai.yml` declares them. The role reads the file from the read-only [svc-ai-models](../svc-ai-models/README.md) store, refuses to start while the store lacks it, links it as Ollama's blob of its digest so `ollama create` uploads no second copy, creates the model from it, and fails unless Ollama then holds the model at that digest. It never pulls a tag from the Ollama library, and an entry without these pins fails the deploy. An entry may also carry `renderer`, `parser` and sampling `parameters`, copied from the config of the Ollama library tag of the same model, because an import from a bare GGUF gets no tool-call parser for many families. They become the `RENDERER`, `PARSER` and `PARAMETER` lines of the model's Modelfile. Only vetted renderer and parser names, allowlisted parameters, numeric values and single-token stop strings pass, so no entry can add a second `FROM` or a `DRAFT`. A model whose directives drift from its entry is created again.
- **Integrations:** Works seamlessly with Open WebUI and Flowise.
- **Offline support:** Fully offline-capable for air-gapped deployments.

## Further resources

- [Ollama](https://ollama.com)
- [Ollama Model Library](https://ollama.com/library)
