# 083 - Agents Phase 6: Board, Channels, Profile Catalog and Management Surfaces

## User Story

As an operator, I want agents to take work from the OpenProject board, talk and ask for approval through Matrix, email and Zammad, start from a catalog of profiles in Open WebUI, n8n and Flowise, and be managed from Open WebUI, so that humans meet the agents where they already work and keep the approval gates.

## Scope

- Phase 6 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), the platform part of phase 4 of its iteration plan. The Board, Profile catalog, Agent firewall, Safety controls and Management surfaces sections of 089 apply. The board migration of `docs/requirements/` stays in [088](088-agents-phase-11-ci-and-acceptance.md).
- Builds on: the control plane of [081](081-agents-phase-4-control-plane.md), the identities of [082](082-agents-phase-5-identity-and-workspaces.md), `utils/orchestrator/channels.py`, `roles/web-app-openproject`, `roles/web-app-matrix`, `roles/web-app-openwebui` and its broker spec.
- Gate: the phase's scenarios through `make agents-verify` and the Open WebUI, n8n and Flowise Playwright specs are green.
- Depends on: [082](082-agents-phase-5-identity-and-workspaces.md).

## Acceptance Criteria

### Orchestrator

- [ ] An OpenProject assignment to the implementer starts the implementer routine.

### Board

- [ ] The orchestrator creates a requirement work package in OpenProject through the API with status `Proposed`.
- [ ] The implementer does not start a `Proposed` work package and starts it after a human sets `Approved`.
- [ ] An agent cannot set `Approved` or `Rejected`.
- [ ] The maintainer starts a failed-run fix without the `Approved` gate.
- [ ] Setting the board URL in the inventory makes every agent use that board instead of the local `web-app-openproject`.
- [ ] An anonymous visitor reads the requirements project and cannot read the security project.
- [ ] The orchestrator's board writes appear under the acting agent's identity in OpenProject's journal.

### Agent firewall

- [ ] The agent is member of exactly the channel rooms derived from its `channel` grants.
- [ ] An `ask` match pauses the routine, the owner receives an approval request, approve resumes and reject aborts.
  - Partial: `build` wraps every `ask` step in `asked` (`agents/routines/contract.py`); `run --owner <account> --homeserver <server>` sends the step's question through the channel contract and waits for the answer, approve resumes and any other answer, none or a missing owner aborts (`TestAsk` in `tests/unit/python/agents/routines/test_contract.py` and `test_main.py`, stub channel). Open: the orchestrator neither delivers the printed request to the owner's Matrix account nor feeds the reply back, and a firewall `ask` hit inside a tool node does not pause yet.
- [ ] An Open WebUI override that would widen a rule is refused.

### Security controls

- [ ] A user-started agent cannot reach an app, MCP tool or channel its owner cannot reach, and loses MCP access within one call after the owner loses the group.
- [ ] `make agents-stop` blocks every agent key, stops every agent container and disables every agent account within one minute; `make agents-start` restores them; the Open WebUI button and the owner's channel command trigger the same target.

### Profile catalog

- [x] The broker lists every role of `agents/roles/` as an OpenAI-compatible model `agent/<role>`.
  - Evidence: `AGENT_ROLES` in the broker env, `profile_catalog`, `model_list` and `resolve` in `roles/svc-ai-agent-broker/files/python/agents.py`; `TestProfileCatalog` in `tests/unit/python/roles/svc-ai-agent-broker/files/test_agents.py` renders the role vars and lists the real catalog.
- [ ] Open WebUI, n8n and Flowise each start a profile through that endpoint (one Playwright spec each).
- [ ] A user without the group `agent-<role>` cannot start that profile.
- [ ] A started agent gets its own accounts on every provisioned provider when it starts, and the reaper removes them when the agent is deleted.

### Channels

- [ ] Team agents log into `web-app-matrix` with their own accounts.
- [ ] A human gives a team agent a task by Matrix DM and receives the result there.
- [ ] Two team agents exchange a coordination message in the team room.
- [ ] A message addressed to an agent account while its instance restarts is delivered after the restart.
- [ ] A failed run and a new pull request produce a Matrix notification.
- [ ] A Matrix reply from the owner's exact local account with the valid nonce approves an `ask` match; a reply without the nonce, from another account, after expiry, as a reaction, or reusing the nonce is refused.
- [ ] No channel reply and no agent account can set a work package to `Approved` or `Rejected`.
- [x] The channel contract has an email and a Zammad implementation, and one unit test drives all three implementations through the same interface.
  - Evidence: the `Channel` protocol with `MatrixChannel`, `EmailChannel`, `ZammadChannel` and `dispatch` in `utils/orchestrator/channels.py`, proven by `tests/unit/python/utils/orchestrator/test_channels.py` (all three through one interface, refusal of a non-account recipient, dispatch order).

### Management surfaces

- [ ] Open WebUI lists the team agents a user may chat with, and a chat reaches the agent.
- [ ] Open WebUI starts, pauses, aborts and triggers a routine.
- [ ] Open WebUI shows running routines, checkpoints, assigned work packages and recent pull requests.
- [ ] Open WebUI changes runtime, repositories, credential overrides and schedule of an agent, only for its owner and the administrator.
- [ ] The Flowise and n8n evaluation is recorded in the orchestrator README with one verdict per management function.
- [ ] Every function judged feasible for Flowise or n8n is implemented and covered by a Playwright spec.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
