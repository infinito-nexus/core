# Test: E2E Playwright Runner

## Description

This Ansible role provides a generic, reusable Playwright end-to-end (E2E) test runner
for the Infinito.Nexus ecosystem.

It automatically discovers roles that ship a Playwright test project under:

- `roles/<application_id>/templates/playwright.env.j2`
- `roles/<application_id>/files/playwright/playwright.spec.js`

A role is considered Playwright-enabled if it provides:

- `roles/<application_id>/templates/playwright.env.j2`

The role then stages the Playwright project to a local staging directory, renders a `.env`
file from `templates/playwright.env.j2`, optionally waits until the application is reachable, and executes
Playwright inside a Docker image derived from the central Playwright package version.

## Overview

This role:

- Discovers Playwright-enabled roles by scanning `roles/*/templates/playwright.env.j2`
- Supports allow-/deny-lists via `test_e2e_playwright_only_roles` and `test_e2e_playwright_skip_roles`
- Stages each Playwright project into `TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR/<application_id>`
- Renders the central `package.json` template into each staged project and injects the central `playwright.config.js`
- Copies every role-specific `files/playwright/*.js` (the `playwright.spec.js` aggregator plus its `test-*.js` scenario modules) into the staged `tests/` directory, and stages `files/playwright/fixtures/` (binary assets such as sample images/videos) alongside them
- Renders `.env` from `templates/playwright.env.j2` using Ansible variables (`application_id`, `domains`, `users`, `applications`)
- Optionally waits until the application responds with HTTP `200` or `302`
- Injects CA trust automatically for `TLS_MODE=self_signed` (via `CA_TRUST.*`), so Playwright accepts self-signed cert chains
- Runs Playwright in Docker with stable browser settings (`--ipc=host`, `--shm-size=1g`)
- Runs the suite once per role on one network it is served on (`lookup('network_siblings', ...)`), picked at random when there are several and kept for the flake retry, with the `.env` rendered for that network's vhost
- Stores per-role reports/artifacts under `TEST_E2E_PLAYWRIGHT_REPORTS_BASE_DIR/<application_id>`, or under `<application_id>+<network>` when the pick is not the canonical network

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Purpose

The purpose of this role is to provide a central E2E test primitive that can be executed
at the end of a deployment (for example, as a post task), without hardcoding tests in the
runner itself.

Each application role stays responsible for its own Playwright tests and configuration.
This role only provides the execution framework.

## Role contract (what application roles must provide)

A Playwright-enabled role must provide:

```
roles/<application_id>/
    templates/playwright.env.j2
    files/playwright/playwright.spec.js
```

For the file-level contract, use [Contributing `playwright.env.j2`](../../docs/agents/files/role/playwright.env.j2.md) and [Contributing `playwright.spec.js`](../../docs/contributing/artefact/files/role/playwright.specs.js.md).

`package.json` and `playwright.config.js` are provided centrally by this role:

- `roles/test-e2e-playwright/templates/package.json.j2` (rendered per-deploy; pins `@playwright/test` from `meta/services.yml.playwright.version`)
- `roles/test-e2e-playwright/files/playwright.config.js` (copied as-is)

## Per-role settings

A tested role declares its Playwright settings under `playwright:` in its own `meta/tests.yml`, read through `lookup('role_tests', application_id, 'playwright.<key>')`. A Jinja value renders with `application_id` bound to the declaring role.

| Key | Purpose |
|---|---|
| `timeout` | Seconds for the role's pass, for specs that legitimately outlast `test_e2e_playwright_run_timeout` |
| `run_after` | Role names whose passes run before this role's pass. Names outside the round constrain nothing; a name that is no role, the role itself, or a cycle fails the run. |

Passes run the `provides: sso` role first, then in deploy order. `lookup('playwright_order', ...)` then moves a role with `run_after` behind the roles it names and leaves every other role in place.

A role whose specs wait on a long background build names every invokable role except itself, so its pass runs last and the earlier passes overlap the build:

```yaml
playwright:
  timeout: 9000
  run_after: "{{ lookup('deployment').all | difference(['web-app-docs']) }}"
```

## Spec secrets

A role whose specs need a credential that must not sit in the world-readable `.env` or in the container environment ships `templates/playwright.secrets.j2` next to `templates/playwright.env.j2`. The runner renders it the same way as the `.env`, with the same `application_id`, `domains` and `domain`, and only when the file exists.

- **Format:** one `KEY=VALUE` per line, `KEY` matching `[A-Z][A-Z0-9_]*`, everything after the first `=` is the value, without quote handling. Blank lines and lines starting with `#` are skipped. Lines end at `\n` only and a value holds no line break: a carriage return, vertical tab, form feed, `\x1c` to `\x1e`, `\x85`, U+2028 or U+2029 fails the pass, so base64-encode a multi-line value in the template and decode it in the spec. This is a format limit, not something the helper can detect: a continuation line after a `\n` that looks like `KEY=...` becomes a secret of its own, and one that starts with `#` is dropped. A bad line, a duplicate key or a key that is invalid or longer than 255 characters fails the pass with the line number in the split file: the runner's rendered file starts with the salt line, so its line 1 is the salt, while a rerun counts the operator's file as it is. No message names a key, prints line text or a value, and a good split prints only the number of files.
- **Files:** `files/spec_secrets.py` writes each value to a file named after its key, mode `0400`, owner `root`, inside a fresh `0700` directory `run.*` below `/tmp/infinito-playwright-spec-secrets` (`PARENT` in the helper, no variable can move it), outside the stage dir. It opens every directory without following a link and touches only the ones it accepts. A parent that is not a `0700` directory of the runner fails every role with the template, naming the path and the fix, `rm -rf -- /tmp/infinito-playwright-spec-secrets`, so the next run recreates it. The Playwright image runs as root and the runner starts it through rootful Docker, so the container reads every file.
- **Mount:** the directory is bind-mounted read-only at `/run/spec-secrets` into that role's container, serial or parallel, through `--mount`, which fails on a missing source instead of creating it. A spec reads `/run/spec-secrets/<KEY>` and never asserts on, logs or attaches a value, since assertion text still reaches the job log and the JUnit report.
- **Capture:** the same run gets `INFINITO_PLAYWRIGHT_NO_CAPTURE=true`, so `files/playwright.config.js` turns trace, screenshot and video off, drops the HTML report, whose step titles record every `fill()` value, and sets `PLAYWRIGHT_NO_COPY_PROMPT`. It also deletes the variables that would bring recording back through the role `.env` or `TEST_E2E_PLAYWRIGHT_COMMAND`: `PW_TEST_REPORTER` (adds a reporter such as `html`), `PLAYWRIGHT_LIST_PRINT_STEPS` (prints step titles to the log), `PLAYWRIGHT_DASHBOARD` (binds the browser for a dashboard), and `DEBUG` and `DEBUG_FILE` (`pw:api` and `pw:protocol` logs carry the values). Playwright still writes `error-context.md` and the failure snapshot, but into `/tmp/test-results` inside the `--rm` container, which goes with the container. `INFINITO_PLAYWRIGHT_KEEP` does not turn them back on.
- **Output:** on a failure, Playwright's own call log carries the `fill()` value and every request header of the failed step, and it reaches the list output, the JUnit report and the GitHub annotations whatever the capture switch says. So the runner starts that container through `files/spec_secrets_mask.py mask`, whose matcher is `files/spec_secrets_match.py`, with `NO_COLOR=1` and `FORCE_COLOR=0`. The masker runs on the host and reads the values from the run directory, never from an argument, variable or the environment.
  - **Masked**, with `***`: every piece of a value at least 8 bytes long (`MASK_MIN`), so the whole value, a prefix such as the 49-character element preview and the parts of a value split by a line break. The masker looks for them in the raw bytes, in the bytes decoded from one of XML entities, percent escapes, form encoding (`+` as a space) and JS or JSON string escapes, and in the bytes decoded from any two of them in a row, the same one twice included, such as JSON inside a JUnit attribute, a double percent-encoded or a form-encoded query inside a URL, or the single-quoted `inspect` form, with ANSI escapes removed from each. It masks the container's stdout and stderr before Ansible or the scheduler sees them, then every file of the run's reports dir, whatever its age, and every file of its stage dir that the run created or changed, except the stage dir's `node_modules`, npm's install tree or the shared read-only mount, where no reporter writes. Right after staging, the deploy keeps the sha256 of every file of the fresh stage dir in `<stage dir>.staged`, beside it and outside every container mount (`spec_secrets_mask.py baseline`), through a new file renamed into place. The list is trusted only when the runner owns it and the stage base dir, which the role creates `root`-owned, and neither is group- or world-writable; otherwise no stage file is trusted. Before a run starts, the masker takes the digests of the stage dir in memory and copies them to the run directory's `.staged` for a scrub after a kill; a stage file with the same digest afterwards stays as it is, so a value that shares 8 bytes with the `.env` or a spec never rewrites what the next rerun reads. The masker reads the values and these digests before the run, so it still masks everything when the run directory goes while the container runs, as it does once the play or rerun shell that owns it is gone. It scans 64 KiB chunks with an overlap, never a whole file at once, rewrites only a file that held a value through a `.masked.*` sibling, which holds masked bytes only, and keeps the container's exit code. A `.masked.*` file is scanned like every other file, whoever wrote it. A suffix automaton over the values makes the matching linear in the output, one step per byte in each of at most 21 decoded views; measured on 1 MB of output dense with values in every encoding, on a host at load 96, that is 8 to 14 s of CPU, 1.2 to 1.9 times the 13 views of a single inner layer.
  - **After a kill:** the serial and parallel runs pass `--cidfile` into the run directory. HUP, INT or TERM make the masker remove the container named in its `.cid`, since the container's PID 1 ignores them, and mask the files before it exits. A SIGKILL skips that and leaves the container writing its reports, so every later scrub, `spec_secrets_mask.py scrub` with the container tool, force-removes the container named in `.cid` first and only then masks every file again: the serial run's `always` section before the directory goes, the parallel run once the scheduler has drained and removed its containers by name; a failure there fails the play. The rerun passes no `--cidfile`; its `EXIT` trap force-removes its named container before the same scrub.
  - **Not masked:** values and pieces shorter than 8 bytes, like masked CI variables: masking a short string such as `admin` or `1234` would blank out unrelated output everywhere and point at the value instead of hiding it, so such a value is no secret worth the name. Unrelated output that shares 8 bytes or more with a value is masked as well, and masking beats syntax: a value that shares 8 bytes with markup, such as `testcase`, turns `<testcase` into `<***`, so the report no longer parses. An interrupted play skips the parallel run's scrub: the maskers still running mask their runs from memory when their containers end, a masker killed as well leaves its files to the next deploy, which wipes the stage dir, and to the next run's scrub of the reports dir, which masks only the values of that run. A scrub killed mid-file leaves its `.masked.*` sibling, which holds masked bytes only. While a container lives, the Docker `json-file` log holds its raw output. Derived forms such as a base64 `Basic` header, a signature or a hash stay the spec's job: wrap every call that carries one in a helper that rethrows a sanitized error, as the GUI's `sendingSecret` does.
- **Cleanup:** the serial run's `always` section removes its directory on success and on failure; the parallel run removes every directory it created once the scheduler has drained. `spec_secrets.py create` hands each directory, already locked with a shared `flock`, to a detached child. The child exits once the directory is gone, and lets go of the lock after a time limit (none for a rerun): the pass's own run timeout (`TEST_E2E_PLAYWRIGHT_RUN_TIMEOUT_EFFECTIVE`) for a serial pass, `TEST_E2E_PLAYWRIGHT_PARALLEL_BUDGET` for a parallel one, because a queued job has no bound of its own before the scheduler starts it, each plus `TEST_E2E_PLAYWRIGHT_MASK_GRACE_SECONDS`, so the masking after a killed run still finds the values. It also watches an owner, and once that is gone, after Ctrl-C, a kill or a cancelled job, it removes the directory itself within a second and exits. The owner is the rerun's shell, or the `ansible-playbook` process (`TEST_E2E_PLAYWRIGHT_PLAY_PID`) only when `ansible_connection` is `local`. Every other connection, such as `docker` in the default swarm flow or `ssh` (including over the swarm VPN), passes 0 because the play's process is not visible on the target, so there the time limit alone applies and the next prune removes the files. Every run starts with `spec_secrets.py prune`, which removes only the `run.*` directories whose lock it can take, so a live run of another deploy or rerun keeps its files; a missing or foreign parent makes the prune skip, never fail.
- **Masking:** the runner uses no `no_log`, which test roles forbid; instead no value reaches an Ansible variable, a command line, a diff, the `.env`, the stage dir or the container environment, and the checksum the copy task reports at `-v` covers a random salt line as well. The size it reports still gives the total length within a few characters.
- **Rerun:** `scripts/tests/e2e/rerun-spec.sh` cannot render the template, so for such a role it takes the rendered lines from the file `PLAYWRIGHT_SPEC_SECRETS_FILE` names (`secrets=<file>` on `make compose-playwright` and `make swarm-playwright`, a path inside the runner container, which the operator owns and the rerun leaves in place), splits them with the same `files/spec_secrets.py`, mounts them the same way, sets the same switch and masks the output and files the same way. It refuses `--reporter`, `--output`, `--trace`, `-c`/`--config` (an alternate config ignores the switch), `--ui` with `--ui-host` and `--ui-port`, and `-u`/`--update-snapshots` (baselines land in the host-mounted stage dir). Before it restages the spec files, it masks every stage file whose digest `<stage dir>.staged` does not hold, so a value an earlier, killed run left in the stage dir, in a new file or appended to the `.env`, is masked before the container starts, while the deployed `.env` stays as it is; without that list, on a stage dir no deploy of this version staged, every stage file holding a value is masked, the `.env` included. Then it restages, so a spec changed since the deploy is never masked before it runs. It runs the container under a name, force-removes it on HUP, INT or TERM, waits for the masking to finish, and on exit, also after a killed masker, force-removes the container, then masks every file again before it removes the directory. A killed rerun shell leaves its container running until it ends, and the child removes the directory; the masker, still running, masks the output and files from memory when the container ends, and if it is killed as well, the next rerun masks what it left before it starts.
- **Unchanged:** the `.env` rendered from `templates/playwright.env.j2` and its `--env-file` stay as they are, and a role without the template deploys as before: no directory, no mount, capture unchanged. Its rerun still replaces the shell with `docker run`, but every rerun, with or without the template, now restages `files/playwright.config.js` first, so a stack staged before the switch existed still honours it.

## Included files

This role ships central Playwright defaults:

- `templates/package.json.j2`: `@playwright/test` version derived from `meta/services.yml.playwright.version`, and `@axe-core/playwright` (WCAG checks through `AxeBuilder`) pinned by `meta/services.yml.playwright.axe_version`
- `files/playwright.config.js`: shared Playwright configuration
- `files/network-leak.spec.js`: guest persona and cross-network leak check, staged next to every role spec and skipped unless `PLAYWRIGHT_NETWORK_LEAK=true`, which the runner sets when the role is served on more than one network

All three are used as central defaults for every app role.

## Variables

### Staging & reports

- `TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR` (default: `/tmp/test-e2e-playwright`)
- `TEST_E2E_PLAYWRIGHT_REPORTS_BASE_DIR` (default: `/var/lib/infinito/logs/test-e2e-playwright`)

### Playwright runtime

- `TEST_E2E_PLAYWRIGHT_IMAGE` (resolved in `vars/main.yml` from `meta/services.yml.playwright.image` + `.version` via `lookup('config', 'test-e2e-playwright', 'services.playwright.image|version')`)
- `TEST_E2E_PLAYWRIGHT_IMAGE_DISTRO` (default: `noble`)
- `TEST_E2E_PLAYWRIGHT_COMMAND` (default: `npm install --no-fund --no-audit && npx playwright test`)

### Discovery filters

- `test_e2e_playwright_only_roles` (default: `lookup('deployment').running`, every role the round deploys, dependencies included)
- `test_e2e_playwright_skip_roles` (default: `[]`)

## Design notes

- The runner is intentionally test-agnostic at runtime: it executes only tests provided by application roles.
- `playwright.version` in `meta/services.yml` is the single source of truth for the default Playwright version; the central `templates/package.json.j2` pins it via the `image_version` filter.
- `templates/playwright.env.j2` acts as the stable marker for discovery and as the source of environment configuration.
- Playwright is executed in Docker for reproducibility and consistent browser dependencies.
- In `TLS_MODE=self_signed`, the role requires `CA_TRUST.cert_host`, `CA_TRUST.wrapper_host`, and `CA_TRUST.trust_name` and fails early if cert/wrapper files are missing.

## How to use

1. Add the two app-specific files:
   - `roles/<application_id>/templates/playwright.env.j2`
   - `roles/<application_id>/files/playwright/playwright.spec.js`
   Follow [Contributing `playwright.env.j2`](../../docs/agents/files/role/playwright.env.j2.md) and [Contributing `playwright.spec.js`](../../docs/contributing/artefact/files/role/playwright.specs.js.md) while creating them.
2. Deploy a round that includes your app (e.g. `make compose-deploy apps=<application_id>`); its specs run with those of every other role the round deploys.
3. Keep `package.json` and `playwright.config.js` centralized in `roles/test-e2e-playwright/` (`templates/package.json.j2` and `files/playwright.config.js`).

Example override for running only one spec:

`-e TEST_E2E_PLAYWRIGHT_COMMAND='npm install --no-fund --no-audit && npx playwright test tests/login.spec.js'`

## Recording

For interactive Playwright recording, use the external repository:

[playwright-recorder](https://github.com/kevinveenbirkenbach/playwright-recorder)

This role no longer ships its own local recording wrapper.
