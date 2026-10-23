# Ollama

## Description

[Ollama](https://ollama.com) is a local model server that runs open LLMs on your hardware and exposes a simple HTTP API. Prompts and data stay on your machines, making it the backbone for privacy-first AI.

## Overview

This role deploys Ollama as a local model server using Docker Compose. It integrates with Open WebUI for chat and Flowise for AI workflow automation, and configures local model caching so models can be reused across sessions or run fully offline.

## Features

- **Local model execution:** Run popular open models (chat, code, embeddings) on your own hardware.
- **HTTP API:** Simple, predictable HTTP API for application developers.
- **Local caching:** Models are cached locally to avoid repeated downloads.
- **Integrations:** Works seamlessly with Open WebUI and Flowise.
- **Offline support:** Fully offline-capable for air-gapped deployments.

## Further resources

- [Ollama](https://ollama.com)
- [Ollama Model Library](https://ollama.com/library)
