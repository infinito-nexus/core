# Tika

## Description

[Apache Tika](https://tika.apache.org/) turns an uploaded file into plain text and metadata. It reads PDF, the Office formats, mail, archives and images.

## Overview

The role runs the `-full` image, which carries the OCR and language packs, and serves it on port 9998 inside the container network only. No port is published and no proxy entry is created.

A consumer reaches it as `http://tika:9998` once it declares `tika` in its own `meta/services.yml` with `enabled` and `shared` set, which is what attaches the consumer to this role's network. `web-app-openwebui` ships that flag and sends `CONTENT_EXTRACTION_ENGINE=tika` with it.

## Features

- **Internal only:** the server listens on the container network; nothing is published to a host port or a proxy.
- **Full extraction set:** the `-full` image ships the OCR and language detection dependencies, so scanned documents are extracted too.
- **Shared instance:** one container serves every consumer that carries the service flag.
