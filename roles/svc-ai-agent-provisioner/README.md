# Agent Provisioner

## Description

Agent Provisioner is the agents control plane for detached, throwaway instances. It offers the instance API those instances register against, provisions their agents' IAM accounts in Keycloak and the federated LDAP directory under the owner's approved ask, holds each instance on a renewable lease, and runs the reaper that revokes an instance once its lease expires.

## Overview

This role deploys a single self-built, standard-library container in Compose and Swarm. The container wraps the committed, stack-free control-plane libraries under `utils/orchestrator/` and `utils/agents/` and exposes them over an OpenAPI instance API. The audit trail persists to `svc-db-postgres`; accounts are created with the provisioner's own rights against Keycloak and the LDAP backend it federates. A registration names an instance by a public key, provisioning is an owner-approved ask, every write rests on a live lease, and audit entries carry no secret values.

## Features

- **Registration:** A throwaway instance registers its name together with a public key through `utils.orchestrator.instance_api`; a later registration of the same name with a different key is refused, and the same key takes over, so a restarted instance keeps its name but a stranger cannot steal it.
- **Provisioning:** The instance requests accounts for its agents under the developer's own login, which becomes the agents' owner; the request is an ask the developer or the live owner approves, and only then does the provisioner create the accounts. Account names come from `utils.agents.naming`, the default account from `utils.agents.accounts`, and the credential-release policy from `utils.agents.keepass`.
- **Leases and reaper:** Each provisioned instance is held on a lease it renews by heartbeat (`utils.orchestrator.instance_api.lease_active`). When the lease expires the reaper revokes the instance's tokens, app passwords and Matrix devices and returns its claimed work packages to `Approved`. `make agents-stop` only suspends; a teardown revokes.
- **Audit ingest:** A throwaway instance spools audit entries locally and sends them with its own sequence numbers; the live provisioner assigns time, sequence and a hash-chained link (`utils.orchestrator.audit`), reports gaps in the spooled sequence, and keeps the chain insert-only so a later edit or deletion is detectable.
- **Secret hygiene:** Every stored audit payload is passed through `utils.agents.redact`, so a token, key or password spooled into a note never reaches the chain; the Keycloak and LDAP admin credentials are read from the environment and never logged.
