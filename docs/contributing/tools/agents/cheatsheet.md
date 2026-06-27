# Cheatsheet 📋

Copy-paste prompt templates the operator can hand to an agent to kick off a workflow. Each prompt routes the agent to its authoritative procedure file; this page is a navigational aid only and MUST NOT be treated as source of truth.

Replace every `<placeholder>` before sending.

Every prompt below instructs the agent to first clarify all open requirements through active listening, then act autonomously through to completion with as few follow-up questions as possible.

## Selection Matrix 🧭

| Situation | Use |
|---|---|
| Building a new feature, app, or larger change | [Development](#development-) |
| Fixing or evolving a single web app role with the deploy/test loop | [Web Development Iteration](#web-development-iteration-) |
| Validating or debugging one or more roles (or every app) across both deploy modes, compose then swarm | [Cross-Mode Roundtrip](#cross-mode-roundtrip-) |
| Running or validating tests for a specific scope | [Testing](#testing-) |
| Writing or updating a Playwright spec for a `web-*` role | [Playwright Tests](#playwright-tests-) |
| Cleaning up code, docs, or roles after a change | [Refactor and Optimize](#refactor-and-optimize-) |
| A GitHub Actions / CI run failed and needs triage | [Pipeline Debugging](#pipeline-debugging-) |
| A local deploy is failing on the host | [Local Deploy Debugging](#local-deploy-debugging-) |
| Operator placed a `*.log` or `*job-logs.txt` file in the workdir for ad-hoc inspection | [Log File Inspection](#log-file-inspection-) |
| Staged changes are ready to be committed | [Commit](#commit-) |
| A branch is ready to be opened as a pull request | [Pull Request Creation](#pull-request-creation-) |
| A branch needs to be pushed, validated via manual CI, and transitioned through the draft → ready-for-review cycle | [Push, Trigger, Pull](#push-trigger-pull-) |
| A new requirement needs to be written | [Requirement Creation](#requirement-creation-) |
| An existing requirement file needs to be implemented end to end | [Requirement Implementation](#requirement-implementation-) |

## Development 🧱

For any change with a documented acceptance scope, [Requirement Implementation](#requirement-implementation-) is the preferred entry point; use this prompt only when no requirement file exists or applies.

```
Follow the instructions from AGENTS.md, develop <feature-or-app> by following the procedure in docs/agents/action/develop.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [develop.md](../../../agents/action/develop.md)

## Web Development Iteration 🔁

For any change with a documented acceptance scope, [Requirement Implementation](#requirement-implementation-) is the preferred entry point; use this prompt only when no requirement file exists or applies.

```
Follow the instructions from AGENTS.md, iterate on web app role <role> by following the procedure in docs/agents/action/iteration/compose.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible. For every failing Playwright test, follow the inner-loop procedure in docs/agents/action/iteration/compose.md together with the procedure in docs/agents/action/iteration/playwright.md. Before every redeploy you MUST run `make compose-exec` and `make compose-inner-run` against the live stack and fully fix and inspect every failure in the container. A new deploy iteration MUST NOT start until every error is resolved and the fix has been empirically verified in-container. You MUST NOT use any commit command, push command, or any command that would require an `ask`-mode approval. You MUST NOT stop the iteration early under any circumstance. Premature termination is explicitly forbidden. The iteration is finished only when every role is green end-to-end.
```

SPOT: [Compose Loop](../../../agents/action/iteration/compose.md)

## Cross-Mode Roundtrip 🔄

```
Follow the instructions from AGENTS.md, then roundtrip-validate every role compose then swarm per docs/agents/action/iteration/roundtrip.md. Drive it with `make roundtrip` with no apps to sweep every application in complexity order. Act autonomously, no questions. On failure: read `${TMPDIR:-/tmp}/roundtrip-<app>-<mode>.log`, drop into the focused loop (docs/agents/action/iteration/compose.md for compose, docs/agents/action/iteration/swarm.md for swarm), confirm the fix in-container before any redeploy, apply the real fix in the repo, then re-run. You MUST NOT run any commit, push, or `ask`-approval command. You MUST NOT stop early. Every 15 minutes you MUST verify the container is still running and not hanging. Done only when every role is green in compose AND swarm.
```

SPOT: [Roundtrip Loop](../../../agents/action/iteration/roundtrip.md)

## Testing ✅

```
Follow the instructions from AGENTS.md, run and validate tests for <scope> by following the procedure in docs/agents/action/testing.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [testing.md](../../../agents/action/testing.md)

## Playwright Tests 🎭

```
Follow the instructions from AGENTS.md, write or update the Playwright test for role <role> by following the procedure in docs/agents/action/iteration/playwright.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible. Ask upfront whether to scope changes to the Playwright files only or also to any other files that cause the tests to fail.
```

SPOT: [playwright.md](../../../agents/action/iteration/playwright.md)

## Refactor and Optimize ♻️

```
Follow the instructions from AGENTS.md, refactor and optimize the affected files by following the procedure in docs/agents/action/refactor.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [refactor.md](../../../agents/action/refactor.md)

## Pipeline Debugging 🛠️

```
Follow the instructions from AGENTS.md, triage the failing CI run at <github-actions-run-url> by following the procedure in docs/agents/action/debug/ci.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [ci.md](../../../agents/action/debug/ci.md)

## Local Deploy Debugging 🧰

```
Follow the instructions from AGENTS.md, debug the failing local deploy of role <role> by following the procedure in docs/agents/action/debug/local.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [local.md](../../../agents/action/debug/local.md)

## Log File Inspection 🔍

```
Follow the instructions from AGENTS.md, inspect the log file <path-to-log> by following the procedure in docs/agents/action/debug/log.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [log.md](../../../agents/action/debug/log.md)

## Commit 💾

```
Follow the instructions from AGENTS.md, commit the staged changes by following the procedure in docs/agents/action/commit.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [commit.md](../../../agents/action/commit.md)

## Pull Request Creation 📤

```
Follow the instructions from AGENTS.md, open a pull request for the current branch by following the procedure in docs/agents/action/pull-request.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [pull-request.md](../../../agents/action/pull-request.md)

## Push, Trigger, Pull 📡

```
Follow the instructions from AGENTS.md, push branch <branch>, run it through the manual-CI draft cycle, and transition the PR to ready-for-review by following the procedure in docs/agents/action/push-trigger-pull.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [push-trigger-pull.md](../../../agents/action/push-trigger-pull.md)

## Requirement Creation ✍️

```
Follow the instructions from AGENTS.md, create a new requirement for <topic> by following the procedure in docs/contributing/requirements.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible. Before every redeploy you MUST run `make compose-exec` and `make compose-inner-run` against the live stack and fully fix and inspect every failure in the container. A new deploy iteration MUST NOT start until every error is resolved and the fix has been empirically verified in-container. You MUST NOT use any commit command, push command, or any command that would require an `ask`-mode approval. You MUST NOT stop the iteration early under any circumstance. Premature termination is explicitly forbidden. The iteration is finished only when every role is green end-to-end.
```

SPOT: [requirements.md](../../requirements.md)

## Requirement Implementation 🚀

If no requirement file exists yet for the work, run [Requirement Creation](#requirement-creation-) first to produce one.

```
Follow the instructions from AGENTS.md, implement requirement docs/requirements/<NNN-topic>.md by following the procedure in docs/agents/action/requirements.md. Begin by clarifying every open requirement through active listening, then act autonomously through to completion with as few follow-up questions as possible.
```

SPOT: [requirements.md](../../../agents/action/requirements.md)
