# Cheatsheet 📋

Each operator workflow has a skill that routes the agent to its authoritative
procedure and drives it — clarifying open requirements first, then acting
autonomously to completion. Most are `i8-` skills specific to this repository; a
few (such as `triage`) are portable skills shared across projects.

## How to use 🧭

Invoke a skill with its slash command, for example `/i8-develop` or `/i8-quality`,
or name the skill in your message to the agent. Supply the concrete target (role,
scope, requirement file, or run URL) in the same message; the skill fills the rest
from its procedure file. Run `make install-skills` to (re)install them.

## Skills 🗂️

| Situation | Skill |
|---|---|
| Building a new feature, app, or larger change | `i8-develop` |
| Iterating a web app role in compose mode | `i8-iterate-compose` |
| Iterating a web app role in swarm mode | `i8-iterate-swarm` |
| Validating every role across both modes, compose then swarm | `i8-iterate-roundtrip` |
| Iterating on `svc-runner` or the self-hosted runner infrastructure | `i8-iterate-runner` |
| Iterating on a GitHub Actions workflow | `i8-iterate-workflow` |
| Writing or updating a Playwright spec for a `web-*` role | `i8-iterate-playwright` |
| Running or validating tests for a specific scope | `i8-test` |
| Running the quality gate (`make quality`) to green | `i8-quality` |
| Cleaning up code, docs, or roles after a change | `i8-refactor` |
| A GitHub Actions / CI run failed and needs triage | `triage` |
| A local deploy is failing on the host | `i8-debug-local` |
| Inspecting a `*.log` or `*job-logs.txt` file dropped in the workdir | `i8-debug-log` |
| Staged changes are ready to be committed | `i8-commit` |
| A branch is ready to be opened as a pull request | `i8-pull-request` |
| Pushing a branch through the manual-CI draft → ready-for-review cycle | `i8-push-trigger-pull` |
| Writing a new requirement | `i8-requirement-create` |
| Implementing an existing requirement file end to end | `i8-requirement-implement` |
