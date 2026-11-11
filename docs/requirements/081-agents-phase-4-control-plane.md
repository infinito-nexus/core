# 081 - Agents Phase 4: Control Plane and Verification Harness

## User Story

As an operator, I want the broker and the orchestrator to discover runtimes, run the agent lifecycle, start routines from triggers and crons, keep routine state across restarts and audit every action, and I want `make agents-verify` to play real scenarios against that stack, so that every later phase is proven by deployed scenarios instead of skipped ones.

## Scope

- Phase 4 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), the first part of phase 3 of its iteration plan. The Runtime contract, Lifecycle, Orchestrator, Routines, Safety controls, Local setup and integration workflows and Iteration plan sections of 089 apply.
- Builds on: `roles/svc-ai-agent-broker`, `roles/svc-ai-agent-orchestrator`, `utils/orchestrator/` (audit, channels, cron, instance_api, webhook), `plugins/lookup/agent_config.py`, `cli/agents/scenarios.py`, `scripts/agents/`, `inventories/bundles/servers/agents/` and the agents workflows.
- Gate: single-role deploys of the broker and the orchestrator with in-container probes, and `make agents-verify` through act in compose mode, are green.
- Depends on: [078](078-agents-phase-1-foundations.md), [079](079-agents-phase-2-tooling-gaps.md), [080](080-agents-phase-3-firewall-compiler.md).

## Acceptance Criteria

### Layout

- [x] Every role's scheduled starts live in its `cron.yml`, a role may list several entries, and the orchestrator runs each entry at its schedule (fixture clock).
  - Evidence: `TestRoleCronEntries` in `tests/unit/python/utils/orchestrator/test_cron.py` fires the real `cron.yml` entries at their schedules; `tick` in `utils/orchestrator/scheduler.py` folds them into one action per routine and `Runner` starts the routine as `python -m agents.routines run <routine>` under the agent's stack lock, which the orchestrator's minute loop (`cron_loop` in `roles/svc-ai-agent-orchestrator/files/python/server.py`) calls (`tests/unit/python/utils/orchestrator/test_scheduler.py`). The image installs LangGraph from `roles/svc-ai-agent-orchestrator/files/requirements.txt` and ships `agents/routines/` with every module it imports (`tests/unit/python/roles/svc-ai-agent-orchestrator/files/test_image.py`).
- [ ] An inventory override under `agents.<role>` changes a field of `agent.yml` and an entry of `cron.yml` on the next deploy, and every consumer reads the merged value through `lookup('agent_config', ...)`.
  - Partial: `test_the_inventory_override_changes_a_field_and_a_cron_entry` in `tests/unit/python/plugins/lookup/test_agent_config.py`; the lookup no longer fails on a `cron.yml` list root (`plugins/lookup/agent_config.py`, `load_yaml_any`). Live: deploy `svc-ai-agent-orchestrator` with an `agents.translator.cron` override and read the rendered cron entries from the container.

### Routines

- [ ] A second run of a routine keeps the first run's output, and both survive a host reboot.
- [x] A failed log write aborts the routine and leaves no orphaned child process.
  - Evidence: `python -m agents.routines run <routine> --log <file>` runs the routine in its own process group through `supervise` (`agents/routines/__main__.py`), which kills that whole group on a failed log write; `test_a_failed_log_write_aborts_and_leaves_no_child` in `tests/unit/python/agents/routines/test_main.py` writes to `/dev/full` and finds neither the child nor its grandchild alive.
- [x] An operator override of a routine policy is accepted, recorded in the run and shown in its result.
  - Evidence: `run --override <policy>=<value>` hands the overrides to the run under `overrides`, records them in the run's `--ledger` and prints them in the result line; a pair without a value is refused (`TestOverride` in `tests/unit/python/agents/routines/test_main.py`).
- [ ] Two stack commands of one agent never run at the same time, and nothing starts on the machine while the quality gate runs.
  - Partial: every routine run takes its agent's `flock` stack lock and waits for a free gate lock (`utils/orchestrator/locks.py`, `Runner` in `utils/orchestrator/scheduler.py`, `tests/unit/python/utils/orchestrator/test_scheduler.py`, `test_locks.py`). Open: the lock directory is the orchestrator's state volume, not a host path the quality gate and the workspaces share, and the gate does not take the lock yet (next item).
- [ ] Starting a quality gate pauses a running translation through `make i18n-pause` before the first gate step and resumes it after the gate; the translator's night and day crons start nothing while the gate lock is held (fixture clock and lock).
  - Partial: `test_the_gate_lock_starts_no_translator_cron` in `tests/unit/python/utils/orchestrator/test_cron.py:70`. Open: no gate lock and no `make i18n-pause` call around the quality gate exist yet.
- [x] An owner hold on a routine survives every later cron firing of that routine and a restart of the orchestrator until the owner lifts it through the management API (fixture: pause instruction, two cron firings, restart).
  - Evidence: `Store` in `utils/orchestrator/holds.py` writes holds through to the orchestrator's state volume, `POST /routines/hold` and `/routines/lift` set and lift them, and the minute loop passes them to `tick`; `test_a_hold_outlasts_two_firings_and_a_restart` in `tests/unit/python/utils/orchestrator/test_holds.py` and `test_an_owner_hold_outlasts_two_firings` in `tests/unit/python/utils/orchestrator/test_cron.py:82`.
- [x] A routine with a recorded owner-only blocker is reported once and not restarted by its cron until the owner clears the blocker through the management API (fixture).
  - Evidence: `POST /routines/block` records the blocker and messages the owner only for a new one, `POST /routines/clear` clears it (`Store.block`, `Store.clear`); `test_a_blocker_is_reported_once_and_starts_nothing_until_cleared` in `tests/unit/python/utils/orchestrator/test_holds.py`.
- [x] The orchestrator reads the gate lock before every routine step and cron start; a routine started while the lock is held waits (fixture lock).
  - Evidence: the minute loop passes `locks.held(..., GATE)` to `tick`, `Runner.start` waits through `locks.wait_gate`, and `contract.build` wraps every node in `gated` when `ORCHESTRATOR_LOCK_DIR` is set; `test_a_start_while_the_gate_lock_is_held_waits` in `tests/unit/python/utils/orchestrator/test_scheduler.py` and `TestGateBeforeEveryStep` in `tests/unit/python/agents/routines/test_contract.py`.

### Runtime contract and lifecycle

- [ ] `web-app-hermes` and `web-app-openclaw` declare themselves as agent runtimes, and Claude Code in `web-app-workspace` does too.
- [ ] The broker and the orchestrator find runtimes through a lookup; a grep finds no hardcoded runtime list in either role.
- [ ] `svc-ai-agent-broker` no longer sets `enabled: true` on `hermes` or `openclaw`, and deploys with only one of them in the inventory.
- [ ] An `always_on` agent (the robot) is running after deploy and is restarted after its container is killed.
- [ ] A trigger for an `on_demand` team agent wakes it through the orchestrator, and the agent is reaped after its idle timeout.
- [ ] With `agents.max_running` reached, a further start waits in the queue and runs when a slot frees, in trigger order.
- [ ] A test proves that `agents.max_running` times the largest runtime reservation plus the infrastructure of the agents bundle fits the per-variant resource budget, and fails when it does not.
- [ ] An `on_demand` user-started agent is spawned on first Open WebUI request and reaped after the idle timeout.
- [ ] Changing `runtime` of a team agent in the inventory switches its runtime on the next deploy.

### Orchestrator

- [ ] `svc-ai-agent-orchestrator` deploys in compose and swarm and passes lint.
- [ ] A routine resumes from its Postgres checkpoint after the orchestrator container restarts.
- [ ] A failed GitHub workflow run starts the maintainer routine.
  - Partial: the webhook re-fetches the run, `classify` raises `workflow_run_failed` and `dispatch.route` starts the maintainer routine (`utils/orchestrator/webhook.py`, `utils/orchestrator/dispatch.py`, `tests/unit/python/utils/orchestrator/test_webhook.py`, `test_dispatch.py`). Open: the deploy passes no `GITHUB_TOKEN`, so the deployed orchestrator audits the webhook without the re-fetch and starts nothing.
- [x] A schedule from the role's `cron.yml` starts the designer and the tuner routines.
  - Evidence: `test_the_designer_and_the_tuner_start_on_their_schedule` in `tests/unit/python/utils/orchestrator/test_scheduler.py` (`agents/roles/designer/cron.yml`, `agents/roles/tuner/cron.yml`).
- [ ] Tool nodes run inside the agent's workspace, not inside the orchestrator container.

### Security controls

- [ ] An issue from a non-collaborator and a fork pull request run start the planner, not the maintainer's ungated path.
  - Partial: `classify` marks both as an outsider's from the re-fetched object and `dispatch.route` sends them to the planner only (`test_an_outsiders_issue_and_a_fork_run_start_only_the_planner` in `tests/unit/python/utils/orchestrator/test_dispatch.py`). Open: the planner has no routine under `agents/routines/`, so the orchestrator logs `agent_without_routine` instead of starting it.
- [x] A webhook without a valid signature, with a replayed delivery id, or with forged payload content is rejected or acted on only through the re-fetched event.
  - Evidence: the orchestrator answers `401` to a bad signature, `400` to a missing delivery id and `200 duplicate` to a replayed one, and `webhook.intake` decides only on the object it re-fetches by id (`tests/unit/python/utils/orchestrator/test_webhook.py`: forged conclusion and author association).
- [ ] `make agents-bootstrap` prints every setup item with its state, fails on a missing required item, shows missing optional items as inactive, and runs as a preflight of the broker deploy.
- [ ] Every tool call, firewall decision, approval and agent channel message appears in the audit database; an update or delete through the audit role is refused, and a tampered entry breaks the hash chain check.
- [ ] Orchestrator checkpoints are encrypted, contain no secret value (fixture test), and expire after the retention period.
- [ ] A workspace cannot reach another workspace through the orchestrator (probe recorded).

### Local setup and integration workflows

- [ ] `call-test-agents-local.yml` runs on pull requests touching `agents/` or an AI role, and `make agents-verify` runs the same file through act.
- [ ] The iteration plan's inner loop works: a change to one role is verified by `make compose-deploy mode=update`, an in-container probe and `make agents-verify scenario=<id>` without a full workflow run.
- [ ] `make agents-verify` deploys the agent infrastructure through act in compose and runs every scenario; the same workflow deploys and runs it in swarm in the CI.
- [ ] `make agents-verify scenario=<id>` reruns one scenario against the running stack without a redeploy.
- [ ] Scenarios replay recorded stub replies for model nodes; `make agents-rerecord` refreshes them; an injection scenario with a hostile stub that follows the injection still makes no tool call outside the agent's grants.
- [ ] Without GitHub or Anthropic credentials in the inventory, their scenarios report `skipped`.
- [ ] The CI runs the same workflow file as `make agents-verify`.
- [ ] `make agents-verify mode=swarm` refuses to start on a worktree slot above 10 and names the fix.
- [ ] The Ollama images are preseeded and no deploy step waits on the registry cache for them.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
