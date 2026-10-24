# Agents Platform

## Purpose

The complete agent infrastructure deployed against a single host, so every
agent scenario runs end to end: the control plane, the server workspace, the
model gateway, and the forges, board, identity and channels the agents act on.

## Target Audience

Maintainers of the agent platform and CI, running the agent scenarios locally
with `make compose-deploy` or through the `call-test-agents-local.yml` workflow.

## Marketing Positioning

- Autonomous Agent Platform
- Self-Hosted AI Operations
- Local Model Gateway
- Scenario-Verified

## Included Components

- svc-ai-agent-broker
- svc-ai-agent-orchestrator
- svc-ai-agent-provisioner
- web-app-workspace
- web-app-agent-fixture
- web-app-keycloak
- svc-db-openldap
- svc-db-postgres
- web-app-gitea
- web-app-openproject
- web-app-nextcloud
- web-app-matrix
- web-app-zammad
- web-app-weblate
- web-app-mailu
- svc-ai-ollama
- svc-ai-litellm
- svc-ai-mcp-adapter
- web-app-openwebui

## Architecture Overview

The broker spawns agent runtimes and hands out short-lived credentials; the
orchestrator runs the routines, receives the webhooks and drives the channels;
the provisioner owns the instance API, the accounts and the lease reaper. The
agents act on the forges, board, identity, channels and mail sink declared
alongside them, and reach the models through the local gateway. `AGENT_FIXTURE_BUNDLE`
is set here so `web-app-agent-fixture` deploys; the fixture carries seeded
findings for the hacker, security and counsel scenarios and refuses to deploy
from any other inventory.
