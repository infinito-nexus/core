# LiteLLM Gateway

## Description

[LiteLLM](https://docs.litellm.ai/) is an LLM gateway that exposes an OpenAI-compatible HTTP API and forwards each request to a configured model backend, local or hosted. Clients authenticate with virtual API keys that the gateway issues and stores in its own database.

## Overview

This role deploys LiteLLM as a shared gateway container in Compose and Swarm deployments, backed by the central PostgreSQL service. The gateway is headless: it binds its HTTP port on the container host and claims no domain of its own, and the browser-facing surface is published separately by the LiteLLM Admin UI. It renders the model list from the interchangeable local backends available on the host, Ollama and LM Studio, and adds the OpenAI, Anthropic and OpenRouter entries whose API key is configured. Once the gateway is up, it provisions one virtual key per consuming application through the gateway admin API.

## Features

- **OpenAI-compatible API:** One HTTP endpoint serves every model listed in the gateway configuration.
- **Backend routing:** Model entries are generated for Ollama and LM Studio when those services run on the host, under the shared alias each model carries so a consumer names one model whichever local backend answers it.
- **Remote providers:** OpenAI, Anthropic and OpenRouter each add their models when a key is configured. The keys are declared in `meta/secrets.yml` with the `type` and `regex` their value must satisfy, and default to the central `API.<provider>.api_key` entry; an unset key leaves that provider's routes unpublished.
- **Configurable remote models:** The published remote models are the `litellm.remote_models` list in `meta/services.yml`, each entry an `alias`, the LiteLLM `model` string and its `provider`, plus an optional `context` in tokens. An inventory replaces the list through `applications.svc-ai-litellm.services.litellm.remote_models`, and a provider without a key slot aborts the deploy.
- **Declared context windows:** A model entry carrying `context` publishes it as `model_info.max_input_tokens`, and an Ollama entry also runs with that window as `num_ctx` instead of the server's default, so a caller's prompt is not silently truncated.
- **Per-consumer virtual keys:** Each consuming application receives its own virtual key, created through the gateway admin API under an alias naming that application.
- **File-based model list:** The model list is mounted as a read-only config file, with database-stored model entries turned off.
- **Managed credentials:** The gateway master key and the admin UI password are generated and kept as role credentials, and the admin UI username is the platform administrator name.
