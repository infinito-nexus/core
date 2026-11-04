# Agent Orchestrator

## Description

Agent Orchestrator is the agents control plane: it loads the routines of the deployed revision, runs each as a LangGraph graph, takes in webhooks and provider polls, fires the cron schedules, speaks to humans and agents through a channel contract, and keeps a hash-chained audit of everything it does.

## Overview

This role deploys a single self-built, standard-library container in Compose and Swarm. The container wraps the committed, stack-free control-plane libraries under `utils/orchestrator/` and exposes them over an OpenAPI management API. Checkpoints and the audit trail live in `svc-db-postgres`; model nodes relay through the shared `svc-ai-litellm` gateway with the orchestrator's own virtual key. The orchestrator reaches each agent workspace through a per-workspace token, so one workspace cannot reach another, and graph state carries secret handles, never secret values.

## Features

- **Routine runner:** Routines of the deployed revision run as LangGraph graphs; only designated nodes call a model through the gateway or an agent through the runtime contract, and the deterministic tool nodes run inside the agent's workspace.
- **Webhook intake:** A webhook is accepted only with a valid signature (`X-Hub-Signature-256` for GitHub and Gitea, the OpenProject and Zammad equivalents); a repeated delivery id is dropped; the event is re-fetched by id from the provider's API and acted on from the fetched data, never from the webhook body. The signature check and the deduplication are the committed `utils.orchestrator.webhook` library.
- **Polling fallback:** When the deployment is not publicly reachable, the orchestrator polls the provider APIs every `services.agent-orchestrator.poll_interval` seconds (default 120) with jitter instead of waiting for a webhook.
- **Cron schedules:** The schedules each role declares in its `cron.yml` fire through `utils.orchestrator.cron`; while the machine's quality gate holds its lock no `start` fires, and a schedule's load condition must hold before it does.
- **Channel contract:** Messages are addressed to agent accounts or human usernames, never to session names (`utils.orchestrator.channels`). Matrix is the first channel, email through `sys-svc-mail` the second, Zammad the third, in the priority the deployment enables.
- **Encrypted checkpoints with retention:** Graph checkpoints are stored in `svc-db-postgres`, encrypted with the LangGraph `EncryptedSerializer` under a key handle, and expire after `services.agent-orchestrator.checkpoint_retention_days`.
- **Hash-chained audit:** Every tool call, webhook, instance event, channel message and routine run is appended to an insert-only audit chain (`utils.orchestrator.audit`); each entry binds the hash of the one before it, so a later edit or deletion breaks the chain and is detectable.
- **Detached instances:** A throwaway instance on a developer machine registers its name with a public key through `utils.orchestrator.instance_api`; a later registration of the same name with a different key is refused, and provisioned accounts are held on a lease the reaper deprovisions once it expires.
