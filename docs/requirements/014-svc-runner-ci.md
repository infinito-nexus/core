# 014 - Dedicated CI Runner via `svc-runner` Role

## User Story

As a developer, I want to run the Infinito.Nexus CI on a dedicated server so that the deploy + test cycle is no longer bound by local hardware restrictions.

## Idea

Add an `svc-runner` role that provisions a dedicated machine as an Infinito.Nexus CI runner, plus a CLI entry point under `cli/deploy/runner/` (path to be created) that drives an Infinito.Nexus deploy against that runner from a developer workstation.

## Acceptance Criteria

### Role: `svc-runner`

- [x] A new role at `roles/svc-runner/` (path to be created) exists and follows the role-meta layout in `docs/contributing/design/services/layout.md` (including `meta/services.yml` with a `lifecycle` key, `meta/schema.yml`, and `tasks/main.yml`).
- [x] When applied to a host, `svc-runner` brings up an Infinito.Nexus-capable CI runner on that host (the runner is the execution environment in which subsequent Infinito.Nexus deploys and tests run).
- [x] The role is compatible with — and exercised by — the CLI script described under **CLI: `cli/deploy/runner/`** below; deploying through that script against a fresh host MUST yield a working runner without manual post-steps.
- [x] `make test` passes with the new role in place.

### CLI: `cli/deploy/runner/`

- [x] A new CLI entry point at `cli/deploy/runner/` (path to be created) is wired into the `infinito` CLI tree the same way the existing [`cli/deploy/dedicated/`](../../cli/deploy/dedicated/) and [`cli/deploy/development/`](../../cli/deploy/development/) commands are.
- [x] Argument parsing MUST use Python's standard-library `argparse` module, matching the convention used by [cli/deploy/dedicated/command.py](../../cli/deploy/dedicated/command.py). Hand-rolled `sys.argv` parsing or third-party CLI frameworks (`click`, `typer`, etc.) MUST NOT be introduced.
- [x] The script accepts the following parameters:
  - `hostname` (**required**) — the target server that will host the runner.
  - `port` (**optional**, MAY be omitted) — SSH/connection port for the target host.
  - `roles` (**required**) — the set of roles to deploy onto the runner (accepts space- and comma-separated lists, matching the normalisation used by [cli/deploy/dedicated/command.py](../../cli/deploy/dedicated/command.py)).
  - `distribution` (**required**) — the target OS distribution of the runner (used to pick distro-specific tasks inside `svc-runner`).
  - `output stream file` (**optional**, with a documented default value) — file path the deploy's stdout/stderr stream is written to; the default MUST be a stable, documented path under `/tmp/`.
- [x] Running the script against a clean host deploys `svc-runner` (plus any additional `roles` passed in) onto that host, and the runner is reachable / healthy at the end of the run.
- [x] `--help` documents every parameter above, including the default value of the output stream file, in the same style as [cli/deploy/dedicated/command.py](../../cli/deploy/dedicated/command.py).

### Tests & Documentation

- [x] A unit-level test covers the CLI parameter parsing (required vs. optional parameters, the output-stream-file default, and the `roles` normalisation).
- [x] The role's `README.md` documents the runner's purpose, the CLI entry point, and how to invoke it end-to-end.
- [ ] This requirement is cross-linked from the implementing PR, and the implementing PR is cross-linked back here per [requirements.md](../contributing/requirements.md).

## Procedure

The implementation of this requirement MUST be executed autonomously by the agent following the iteration loop defined in [workflow.md](../agents/action/iteration/workflow.md). The following rules apply for the entire run and are non-negotiable:

- [x] **Clarifying questions only at the start.** Any open question, ambiguity, or missing decision (e.g. which CI runner technology, what the `distribution` parameter switches, how `roles` is interpreted, what the `output stream file` default is, lifecycle starting tier, secrets/registration-token source) MUST be raised once at the very beginning of the run, in a single batched question round, BEFORE any file is changed. Once those questions are answered, the agent MUST NOT pause for further clarification — additional ambiguities discovered mid-run MUST be resolved by the agent using its best judgement, recorded in the role's `README.md` or a code comment, and revisited only at PR review.
- [x] **Iteration loop.** The agent MUST follow the [Workflow Loop](../agents/action/iteration/workflow.md) for every change to GitHub Actions workflows the implementation touches, and the [Role Loop](../agents/action/iteration/role.md) for every change inside `roles/svc-runner/`. The agent MUST NOT skip the loop's debug-locally step in favour of remote CI reruns.
- [x] **No `ask` prompts mid-run.** The agent MUST NOT trigger any tool call that routes through `permissions.ask` in [.claude/settings.json](../../.claude/settings.json) during implementation. Where a tool would otherwise route through `ask`, the agent MUST select an equivalent already covered by `permissions.allow`, or rephrase the operation to fit the sandbox. The single permitted exception is the final commit at the end of the run.
- [x] **No interruptions.** Bug fixes, deploy failures, lint failures, `make test` failures, healthcheck flaps, and similar issues MUST be resolved at their root inside this same iteration without prompting the operator. Workarounds, ad-hoc skips, retry-until-green loops, or "track in a follow-up" deferrals MUST NOT be used.
- [x] **One commit at the end.** The agent MUST NOT create any intermediate commit. ALL changes (role, CLI, tests, documentation, and the ticked checkboxes in this document) MUST be combined into ONE commit, created only after every Acceptance Criterion above is checked off (`- [x]`) and `make test` is green. Per-step commits, checkpoint commits, and partial commits MUST NOT be created. The agent MUST NOT push; the operator runs `git-sign-push` outside the sandbox per [CLAUDE.md](../../CLAUDE.md).
