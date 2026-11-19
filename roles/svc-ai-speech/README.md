# whisper.cpp

## Description

[whisper.cpp](https://github.com/ggml-org/whisper.cpp) runs OpenAI's Whisper speech recognition models on the CPU. Its server takes an audio or video file over HTTP and answers with the transcript in the JSON shape of OpenAI's transcription API.

## Overview

The role runs the upstream CPU image pinned to the commit of release v1.9.5 and serves `whisper-server` on port 8080 inside the container network only. No port is published and no proxy entry is created, so no upload passes through OpenResty and no body-size limit applies on the way.

The server answers `POST /v1/audio/transcriptions`, the route an OpenAI client appends to the base URL `http://speech:8080/v1`. It converts every upload with ffmpeg first, so any container ffmpeg reads works, the WebM of a Talk recording with its video track included. It detects the spoken language unless the request names one.

The model is `ggml-small-q5_1.bin` from `ggerganov/whisper.cpp` on Hugging Face, pinned in `meta/networks.yml` to a commit, its sha256 and its size. [svc-ai-models](../svc-ai-models/README.md) fetches it once into the shared model store, and the container mounts that store read-only, so the store is this role's model cache: no deploy and no swarm node downloads the model a second time, and the container starts only on a node whose store holds it.

A consumer reaches the server once it declares `speech` in its own `meta/services.yml` with `enabled` and `shared` set, which attaches it to this role's network. `web-app-nextcloud` ships that flag: while this role is part of the deployment and `integration_openai` is enabled, Nextcloud sends its speech-to-text requests here and Talk transcribes and summarizes stored recordings.

## Features

- **OpenAI-compatible route:** `/v1/audio/transcriptions` takes a multipart upload and answers `json`, `text`, `srt`, `vtt` or `verbose_json`, with segment timestamps in the last.
- **Whole recordings:** the server sets no upload limit, holds one request at a time and keeps answering its health check while it transcribes; `services.speech.request_timeout` (3600 s) is the time a consumer waits for one recording.
- **CPU only:** inference runs on as many threads as `services.speech.cpus` grants; the upload and its 16 kHz WAV, about 450 MB per recorded hour of a Talk video recording, go to `/tmp` until the answer is sent.
- **Pinned model:** the model is verified against its digest before it enters the store, and the store is read-only inside the container.
- **Internal only:** the server has no authentication, so it listens on the container network alone and only the roles that carry the `speech` flag join that network.

## Further Resources

- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- [whisper.cpp server](https://github.com/ggml-org/whisper.cpp/tree/master/examples/server)
- [ggml models](https://huggingface.co/ggerganov/whisper.cpp)
