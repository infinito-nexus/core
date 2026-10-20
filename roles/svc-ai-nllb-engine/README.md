# NLLB-200

## Description

[NLLB-200](https://huggingface.co/facebook/nllb-200-distilled-600M) is a sequence-to-sequence machine translation model covering 202 language-script combinations. It is a translation model rather than a chat model: the decoder is conditioned on a target language token, so it renders into a language instead of being asked to.

## Overview

This role serves one NLLB-200 checkpoint over HTTP as an internal engine without a browser surface. The gateway [`web-svc-translate`](../web-svc-translate/) consumes it over the shared overlay network; nothing publishes it to the internet.

The surface speaks FLORES-200 codes (`deu_Latn`, `bel_Cyrl`, `amh_Ethi`), which is what the model itself carries. The ISO 639-1 codes the rest of the repository is keyed by are mapped in the gateway, in `translate_gateway/flores.py`, together with the languages of `meta/languages.yml` that NLLB has no code for at all.

## Features

- **Two routes:** `GET /languages` lists the FLORES-200 codes the loaded checkpoint carries, `POST /translate` takes `{"source", "target", "text"}` and answers `{"translation"}`.
- **Local inference:** the model runs inside the container, no request leaves the deployment.
- **Weights on a volume:** the checkpoint is downloaded once into `nllb_models` and reused across restarts.
- **CPU or GPU:** the build installs the CPU-only torch wheels unless the deploy resolved a usable GPU.

## Checkpoints

`services.nllb-engine.model` selects the checkpoint. The sizes upstream publishes, with the resident memory the server needs for them in float32 and their relative quality:

| Checkpoint | Parameters | Weights on disk | Resident | Quality |
| --- | --- | --- | --- | --- |
| `facebook/nllb-200-distilled-600M` | 600M | ~2.5 GB | ~3 GB | the floor; distilled from the 54B teacher and still a translation model on every pair |
| `facebook/nllb-200-distilled-1.3B` | 1.3B | ~5.5 GB | ~6 GB | roughly +2 chrF++ over the 600M on the FLORES-200 average, most of it on low-resource pairs |
| `facebook/nllb-200-1.3B` | 1.3B | ~5.5 GB | ~6 GB | the dense model the 1.3B was distilled towards; between the two distilled ones |
| `facebook/nllb-200-3.3B` | 3.3B | ~17.6 GB | ~18 GB | roughly +1 chrF++ over the 1.3B, at three times the memory and latency |
| `facebook/nllb-moe-54b` | 54B | ~220 GB | out of reach | the research model, not deployable on a single node here |

The role declares its resources for the 600M checkpoint. A larger one needs `mem_reservation`, `mem_limit` and `min_storage` of `meta/services.yml` raised with it.

## Further resources

- [No Language Left Behind (paper)](https://arxiv.org/abs/2207.04672)
- [FLORES-200 language codes](https://github.com/facebookresearch/flores/blob/main/flores200/README.md)
