# 084 - Agents Phase 7: Agent Roles at Work

## User Story

As an operator, I want the reviewer, planner, coordinator, operator, tester, translator, documenter, release, security, hacker, counsel, support and tuner roles to run their routines on the deployed platform, so that each role does its documented work end to end under the firewall and the approval gates.

## Scope

- Phase 7 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), the routines part of phase 4 of its iteration plan. The Agent roles, Role files and Routines sections of 089 define each role's work, rules and graph.
- Builds on: the routine graphs under `agents/routines/`, the scenarios under `agents/scenarios/`, `roles/web-app-agent-fixture`, `utils/i18n/`, `cli/build/i18n`, and the platform surfaces of [083](083-agents-phase-6-platform-surfaces.md).
- Gate: every role's scenarios through `make agents-verify` are green in compose and in swarm.
- Depends on: [083](083-agents-phase-6-platform-surfaces.md).

## Acceptance Criteria

### Routines

- [ ] The negative control node turns a guarded spec red and back to green on a fixture role.

### Security controls

- [ ] A seeded prompt injection in an issue, a pull request comment, a ticket, an email and a CI log makes no agent call a tool outside its grants, leak a secret, or skip the `Approved` gate (one scenario each).
- [ ] An autonomous agent's write to `agents/firewall/`, `agents/routines/`, an `AGENTS.md`, a `SOUL.md`, the firewall compiler or `.github/workflows/` is denied, and a pull request touching them is labelled by CI and gets no `recommend merge`.

### Additional agent roles

- [ ] reviewer: an agent pull request with a missing evidence comment gets `changes requested`; a clean one gets `recommend merge`; the reviewer never reviews its own pull request. Partly met: the routine decides all three (`agents/routines/reviewer.py`, `agents/routines/tools/review_checklist.py`, `tests/unit/python/agents/routines/test_reviewer.py`); posting the verdict on the forge from the deployed orchestrator is not wired yet.
- [ ] reviewer: a pull request whose new spec has no negative control gets `changes requested`. Partly met: the routine routes a changed spec without a passing control to `changes requested` (`tests/unit/python/agents/routines/test_reviewer.py`); posting the verdict is not wired yet.
- [ ] planner: an issue becomes a `Proposed` work package with user story and checkable criteria, linked to the issue.
- [ ] planner: a second issue with the same content is linked to the existing work package instead of creating a new one.
- [x] coordinator: two agents requesting a CI deploy of the same repository at once get the slot one after the other.
  - Evidence: `SlotQueue` in `utils/orchestrator/locks.py` behind the orchestrator's `POST /ci/slot` and `/ci/release`; `test_two_concurrent_requests_are_served_in_turn` in `tests/unit/python/utils/orchestrator/test_locks.py`.
- [ ] coordinator: diverging version pins between two feature branches are reported to both owners before they meet.
  - Partial: `agents/routines/coordinate.py` decides the drift through `version_pin_drift` and addresses the report to both owners' accounts, never to a session (`tests/unit/python/agents/routines/test_coordinate.py`). Open: the read of both branch heads is a stub node, no webhook raises `branch_divergence` and the coordinator has no cron entry, so nothing starts the routine yet, and the delivery needs a deployed channel.
- [ ] operator: a seeded alarm (full disk, expiring certificate, failed backup) starts its runbook routine and ends as a work package with timeline and cause.
- [ ] operator: a backup restore waits for the owner's approval.
- [ ] tester: a seeded spec that cannot fail is detected by its negative control and hardened in a pull request.
- [ ] tester: a coverage gap between `meta/services.yml` and the specs becomes a pull request with the missing spec.
- [ ] translator: new strings get machine translations through `web-svc-translate` as Weblate suggestions, and a human-reviewed string stays unchanged.
- [ ] translator: a merge that adds translatable strings is queued, and the cron start at 23:00 UTC runs `i18n-extract`, `i18n-prune`, `i18n-translate` and `i18n-retry` without a human running them.
- [x] translator: at 23:00 UTC the night cron starts or resumes translation regardless of load, and at 07:00 UTC it pauses it and hands over to the day rule (fixture clock).
  - Evidence: `tick` in `utils/orchestrator/scheduler.py` folds the cron entries and the measured load into one action per routine, and `Runner.apply` starts the run, stops its process group on `pause` and continues it on the next `start`; the orchestrator's minute loop passes its measured sample and acts on both actions (`cron_loop` and `act` in `roles/svc-ai-agent-orchestrator/files/python/server.py`). `test_the_night_starts_the_morning_pauses_and_the_day_resumes` and `test_the_night_resumes_a_day_pause_regardless_of_load` in `tests/unit/python/utils/orchestrator/test_scheduler.py`.
- [x] translator: during the day, a tick with CPU and GPU below 30 % starts or resumes translation, and a tick with CPU or GPU above 95 % pauses it (fixture load figures).
  - Evidence: `conditions` in `utils/orchestrator/load.py` holds the 30 % and 95 % thresholds, `tick` in `utils/orchestrator/scheduler.py` turns them into the day action, and the orchestrator's minute loop samples the load through `lane_load` in `utils/orchestrator/probe.py` and hands the pair to `tick` (`cron_loop` in `roles/svc-ai-agent-orchestrator/files/python/server.py`). `test_cpu_and_gpu_below_30_start` and `test_cpu_or_gpu_above_95_pauses` in `tests/unit/python/utils/orchestrator/test_load.py`, `test_a_measured_day_tick_starts_or_pauses` in `tests/unit/python/utils/orchestrator/test_scheduler.py`.
- [x] translator: the day rule ignores the translation lane's own load, so a running translation at high own load with an idle rest of the system is not paused (fixture).
  - Evidence: `lane_sample` in `utils/orchestrator/sample.py` parses the lane container's own CPU from `docker stats` and its GPU from the `nvidia-smi pmon` rows of its processes, and `rest_of_system` in `utils/orchestrator/load.py` takes it out of the host's figure; `test_a_busy_lane_on_an_idle_rest_of_the_system_is_not_paused` and its red fixture in `tests/unit/python/utils/orchestrator/test_sample.py`. The orchestrator's minute loop measures it where `INFINITO_INFRA_RUNNER_CONTAINER` and the `docker` CLI are present (`lane_load` in `utils/orchestrator/probe.py`, called by `cron_loop` in `roles/svc-ai-agent-orchestrator/files/python/server.py`).
- [ ] translator: on a host where `accelerated()` is false, the GPU condition counts as met. Partly met: `conditions(..., accelerated=False)` in `utils/orchestrator/load.py` and `tick` count the GPU half as met (`test_the_gpu_condition_counts_as_met` in `tests/unit/python/utils/orchestrator/test_load.py`, `test_without_a_gpu_the_gpu_half_counts_as_met` in `tests/unit/python/utils/orchestrator/test_scheduler.py`). Open: the orchestrator passes whether `nvidia-smi` answered (`lane_load` in `utils/orchestrator/probe.py`), not `accelerated()` from `utils/i18n/libretranslate.py`, so a host with a GPU and `INFINITO_GPU_COUNT=0` still judges the GPU.
- [ ] translator: `make i18n-pause` pauses the tools lane container and `make i18n-resume` continues it with its models and connections intact; no request leaves the lane while it is paused (probe recorded).
- [x] translator: an entry that fails the separate `make test-oracle` judgement is retranslated in the next window with the engine that produced it excluded.
  - Evidence: the judge pass empties each failed sample and moves its engine into a `judge-failed:` mark (`tests/oracle/test_translation_score.py`, `record_judged` and `fail_judgement` in `utils/i18n/translate.py`), `one_catalog` in `cli/build/i18n/__main__.py` groups the pending entries by those marks and passes them to the client as `exclude` (`utils/i18n/client.py`); fixtures in `tests/unit/python/utils/i18n/test_translate.py` and `tests/unit/python/cli/build/i18n/test_main.py`, recorded as `UT-TRANSLATOR-JUDGE-EXCLUDE` in `agents/criteria.yml`.
- [ ] translator: after `agents.translator.max_attempts` failed attempts an entry is no longer retried, stays marked for a human, and is listed in the translator's report (fixture of a string every engine fails).
- [x] translator: the machine-translation marker of every catalog entry names the engine that answered (fixture with two engines).
  - Evidence: the gateway returns the answering engine per entry (`roles/web-svc-translate/files/python/translate_gateway/app.py`), the client keeps it (`utils/i18n/client.py`, `tests/unit/python/utils/i18n/test_libretranslate.py`), `apply` writes it into the mark (`utils/i18n/translate.py`, `utils/i18n/catalog.py`); the two-engine fixture with its red fixture is `tests/unit/python/utils/i18n/test_translate.py`, recorded as `UT-TRANSLATOR-ENGINE-MARK` in `agents/criteria.yml`.
- [ ] translator: the judge pass of a full night stays within its budget of about one hour of the window, measured on the host (recorded duration).
- [ ] translator: each language gets its own pull request with only that language's catalogs, and no language pull request contains algorithm changes.
- [ ] translator: a language whose catalog fails verification (empty or fuzzy entry, `msgfmt --check` error, changed placeholder or protected span, lost glossary term) gets no pull request and is reported (one fixture per failure kind).
- [ ] translator: a language whose sampled chat-judge level falls below its last accepted level gets no pull request, and a judge reply without a level aborts that language's verification.
- [ ] translator: the language set equals `domain_languages()` for each domain, only languages with changed catalogs get a pull request, and a language without a docs catalog gets it created in its first pull request.
- [ ] translator: an algorithm pull request carries the benchmark table per language, and a change that lowers any language's score is discarded (fixture).
- [ ] translator: the evaluation set of each language is built from human-reviewed Weblate strings and is not used as translation input.
- [ ] documenter: a merged pull request that changes a role's variables produces a README pull request that matches them, with the docs build green.
- [ ] release: a green default branch produces a release draft with notes; the tag waits for approval.
- [ ] security: a seeded vulnerable dependency becomes a work package in the confidential security project.
- [ ] security: a seeded CVE feed entry for a pinned image produces one work package per affected role with the advisory id, the affected and the fixed version, and, where the fix is a public bump, a GitHub issue handed to the maintainer (fixture feed).
- [ ] security: the deployed-component inventory and the hardening floor are built from registry and manifest metadata with no image pull and no request to a running instance (probe recorded).
- [ ] hacker: every seeded finding of the fixture app becomes a work package in the confidential security project with severity, affected role and reproduction steps, and without live secrets.
- [ ] hacker: the analysers report the fixture app's seeded weaknesses (vulnerable dependency, missing security header, weak TLS) as findings (one fixture per analyser).
- [ ] hacker: credential brute forcing runs only against seeded test accounts, stays under the lockout threshold, stops at the first proof, and locks no account out of service (fixture with a seeded weak test credential and a seeded throttle).
- [ ] hacker: every failed check and a failed scan run send an email to the security contact that carries only severity and link.
- [ ] hacker: a scan against a target outside `agents.hacker.targets`, or against an internal port, is refused by the firewall (probe recorded).
- [ ] hacker: without `agents.hacker.targets` the hacker does not start; a production run waits for the owner's approval of that run.
  - Partial: the `D1` decision of `agents/routines/hacker_scan.py` ends a run without targets at `D0` before any scan, and the owner ask `H1` is the only edge into the scan (`tests/unit/python/agents/routines/test_hacker_scan.py`, hacker diagram in [089](089-agents-restructuring.md)). Open: the orchestrator does not pass `agents.hacker.targets` into the run state yet, and the wait on `H1` needs the runner's `ask` pause ([083](083-agents-phase-6-platform-surfaces.md)).
- [ ] counsel: every seeded legal finding of the fixture tree becomes a work package in the confidential legal project with severity, check, location, licence or law, proposed fix and evidence, and every report states that it is no legal advice.
- [ ] counsel: a second run over the unchanged fixture tree updates the existing work packages and opens none.
- [ ] counsel: the seeded build-only copyleft dependency is refuted as a blocker by the dialectic and filed as a finding (fixture).
- [ ] counsel: a new blocker sends an email to the legal contact that carries only severity and link, and the release role refuses to tag while that blocker is open (fixture).
- [x] counsel: the Monday 02:00 UTC cron entry starts a full run, and a changed lockfile on the default branch starts a run scoped to that change (fixture clock and webhook).
  - Evidence: `test_the_counsel_starts_a_full_run_on_monday_at_0200` in `tests/unit/python/utils/orchestrator/test_scheduler.py`; a push whose re-fetched commit changes a lockfile raises `dependency_manifest_changed` with the changed files as scope (`test_a_lockfile_change_on_the_default_branch_is_a_scoped_trigger` in `test_webhook.py`), which `dispatch.route` sends to the counsel's `legal_audit` (`test_dispatch.py`) and `Runner` starts with one `--scope` per file (`test_a_scoped_start_passes_every_changed_file`).
- [ ] counsel: the instance probe reports the fixture app's third-party font host and its cookie set before consent; without `agents.counsel.targets` the report names the instance checks as skipped.
- [ ] counsel: a request to a target outside `agents.counsel.targets` and any write request to an instance are refused by the firewall (probe recorded), and a full run leaves no commit, push or file change.
- [ ] hacker: no scan sends more requests per second than its configured rate limit.
- [ ] support: a new Zammad ticket gets a drafted answer with cited sources as internal note, drawn only from public docs, role READMEs and approved answers with customer data removed.
- [ ] support: the approval view shows the full outgoing text and every attachment.
- [ ] support: the answer reaches the customer only after the owner approves it; a rejection with a remark produces a revised draft.
- [ ] support: a defect described in a ticket becomes a `Proposed` work package linked to the ticket.
- [ ] support: a draft never contains a secret, an internal hostname or another customer's data (fixture test).

### End to end

- [x] The tuner discards a before and after comparison that was measured while another gate, deploy or translation shared the machine (fixture).
  - Evidence: the bench step of `agents/routines/perf_sweep.py` records on both sides the jobs `machine_neighbours` in `agents/routines/tools/bench_guard.py` reads from the machine's lock directory (gate lock, the translator's and every other agent's stack lock), and the guard step discards the comparison (`TestBenchNeighbours` in `tests/unit/python/agents/routines/test_perf_sweep.py`, `TestMachineNeighbours` in `tests/unit/python/agents/routines/tools/test_bench_guard.py`).
- [x] The tuner keeps a hot path in Python when the measured cost is process spawns or round trips, and proposes another language only for a measured CPU-bound loop that runs on every deploy (fixture).
  - Evidence: the deterministic `cost` step before the `pick` model step classifies every scanned task through `measured_cost` in `agents/routines/tools/bench_guard.py`; the guard step judges the picked candidate by that classification, never by a cost the model claims, and pins it as `measured_cost` for the report (`TestCostBeforePick` in `tests/unit/python/agents/routines/test_perf_sweep.py`, `TestMeasuredCost` in `tests/unit/python/agents/routines/tools/test_bench_guard.py`).

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
