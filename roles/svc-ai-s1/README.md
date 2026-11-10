# System One

## Description

Self-hosted System One decision service. It answers typed questions (`choice`, `score`, `noul`) over a non-autoregressive encoder instead of generating text, on the `POST /v1/systemone` contract.

## Overview

[`svc-ai-litellm`](../svc-ai-litellm/) publishes one routing alias. When this service is deployed, the gateway's pre-call hook asks it which of the eligible models should answer, passing the prompt as the state and the surviving aliases as the options of a single `choice` question. `services.litellm.router.strategy` follows `services.s1.enabled`, so deploying this role is what switches the gateway from a weighted score to a System One decision.

`services.s1.flavor` selects which implementation answers that contract. `laya` runs [Laya](https://huggingface.co/convaiinnovations/laya), the default; `torch` and `onnx` run [jeff](https://github.com/logan-markewich/jeff) over a GLiFormer encoder, which is what the role carried before. Neither upstream ships a container image, so the role builds one and bakes the checkpoints into it. Baking keeps the deploy free of a download at container start, which is the failure mode a sibling role's model pull already hit.

## Features

- **One contract, three flavors.** `laya` serves multilingual checkpoints and preloads them at start; `torch` runs the GLiFormer checkpoint as published; `onnx` exports an int8 graph at build time and needs roughly a quarter of the memory. Every flavor answers the same `POST /v1/systemone`, so the gateway does not know which one it asked.
- **Typed answers, no generation.** A routing decision costs one forward pass over an encoder, not a completion.
- **Build-time model.** The checkpoint is a cached image layer rather than a download the first container start waits for.
- **Bearer authentication.** An empty key list would disable auth, so the role always renders one.

## Settings

| Setting | Meaning |
| --- | --- |
| `services.s1.flavor` | `laya`, `torch` or `onnx`; the role refuses anything else |
| `services.s1.model_alias` | alias the API accepts in a request's `model` field |
| `services.s1.request_timeout` | seconds the gateway waits for a routing answer |
| `services.s1.laya.checkpoints` | checkpoints the `laya` flavor bakes, each a `name` the server preloads and the `repo` it comes from |
| `services.s1.jeff.ref` | upstream commit the `torch` and `onnx` flavors build from; upstream publishes no tags |
| `services.s1.jeff.model_repo` | Hugging Face repository those flavors download at build time |
| `secrets.credentials.api_key` | bearer key the server accepts |

## Limits that shape the caller

Both flavors cap the state and the option count and answer HTTP 422 above them, so the gateway truncates the prompt to `services.litellm.router.state_chars` before asking. The `laya` flavor shares a fixed token budget across the options of one question, so accuracy falls off well before its own cap; the deployments here put a handful of model aliases to it, far below where that matters.
