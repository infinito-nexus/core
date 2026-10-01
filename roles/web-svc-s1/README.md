# System One API

## Description

Public vhost for the System One decision service. It serves [`svc-ai-s1`](../svc-ai-s1/) at `s1.ai.<domain>` so a client outside the deployment can ask it a typed question over the same `POST /v1/systemone` contract the gateway uses.

## Overview

This role ships no container. It renders one vhost through [`sys-stk-front-proxy`](../sys-stk-front-proxy/) and forwards to the container `svc-ai-s1` already runs, the way [`web-app-litellm`](../web-app-litellm/) fronts `svc-ai-litellm`. Deploying it without `svc-ai-s1` leaves the vhost answering nothing.

Callers authenticate with the bearer token `svc-ai-s1` already requires: the proxy passes `Authorization` through untouched and adds no credential of its own, so there is no second secret to rotate and the backend stays the single place that decides who may ask.

## Features

- **No second service.** A vhost and nothing else; the answer comes from the container `svc-ai-s1` runs.
- **One credential.** The bearer the backend issues is the bearer the caller sends.
- **Same contract.** `POST /v1/systemone` as the gateway speaks it, plus the `GET /health` the backend already serves.

## Further Resources

- [svc-ai-s1](../svc-ai-s1/README.md)
