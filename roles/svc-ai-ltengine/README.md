# LTEngine

## Description

[LTEngine](https://github.com/LibreTranslate/LTEngine) is a machine translation server that speaks the LibreTranslate API and answers it with a local large language model through [llama.cpp](https://github.com/ggml-org/llama.cpp). Translation quality for many pairs is higher than a lightweight transformer model reaches, at the cost of memory and latency.

## Overview

This role builds LTEngine from the upstream sources at a pinned commit and runs it as an internal engine without a browser surface. The gateway [`web-svc-translate`](../web-svc-translate/) consumes it over the shared overlay network; nothing publishes it to the internet.

## Features

- **LibreTranslate API:** `POST /translate`, `POST /detect` and `GET /languages` in the published request and response shapes.
- **Local inference:** the model runs inside the container, no request leaves the deployment.
- **Weights on a volume:** the GGUF file is downloaded once into `ltengine_models` and reused across restarts.
- **Built from source:** upstream ships no release image, so the role compiles the pinned commit against its own base images.

## Further resources

- [LTEngine](https://github.com/LibreTranslate/LTEngine)
- [Supported models](https://github.com/LibreTranslate/LTEngine#models)
