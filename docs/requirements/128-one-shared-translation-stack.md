# 128 - One Shared Translation Stack

## User Story

As an operator who runs many checkouts, agents and repositories on one workstation, I want one local translation stack per machine that every repository translates its gettext catalogs through, so that no checkout starts engines and models of its own, every model is downloaded once, and every repository serves the languages of core's `meta/languages.yml` from the same gateway.

## Background

The operator ordered this on 2026-11-14 at 11:59 and picked the details around 12:10. Translations are low priority.

### Today

- Every checkout runs its own tools lane: `compose/tools.override.yml` (removed) adds a privileged `tools` service to the checkout's compose project whenever the tools keys are set (`TOOLS_LANE_KEYS` in [env.py](../../cli/administration/deploy/development/env.py)). `make i18n-translate` deploys the bundle of `utils/i18n/gateway.py` (the LibreTranslate engine, LTEngine, NLLB, Ollama, LiteLLM, System One and `web-svc-translate`) into that service through the inventory `~/inventories/infinito-tools` (`utils/i18n/libretranslate.py`, `utils/inventory/tools.py`, `utils/inventory/tools_vars.py`, [tools.yml.j2](../../inventories/development/tools.yml.j2)). `make i18n-pause` and `make i18n-resume` paused the lane container a caller named. Two worktrees that translate run two bundles; only the models under `INFINITO_TOOLS_MODELS_HOST_PATH` are shared.
- `make test-oracle` brings the same lane up through `python -m utils.inventory.tools`, and `make i18n-tune` deploys the engine through `utils/i18n/libretranslate.py`. The lane has no idle stop: it runs until the checkout's stack goes down.
- Core's catalogs are the domains `core` and `docs` under `locale/<code>/LC_MESSAGES/` ([054](054-gettext-catalogs-libretranslate.md)); `make i18n-extract` and `make i18n-translate` knew only these two domains. The root and domain interface of the team page (worktree `feature/i18n-custom-root-domain`, never committed) is folded into this requirement's branch.
- The infra runner that is to host the tools is [092](092-local-stack-architecture.md) Phase 5, and moving the tools into it is its Phase 6; both are open, and neither `make infra-up` nor `inventories/development/infra.yml.j2` exists yet. Its Phases 1 to 4 are partly built: bounded caches with `make cache-evict` and the disk floor, the stack helper with `INFINITO_STACK_NAME`, and the stack declaration `compose/stacks.yml`, which already names `tools` as an on-demand stack.
- Repositories outside core:
  - `infinito-nexus/gui` (store) runs a LibreTranslate container of its own (`compose/services/libretranslate.compose.yml`, `scripts/i18n/translate.py`, its i18n workflow `.github/workflows/i18n.yml`).
  - `infinito-nexus/security` calls `web-svc-libretranslate` at runtime (`translation.url` in `ansible/roles/web-app-cst-security-check/meta/services.yml`, `src/inspect.rs`).
  - `infinito-nexus/team` already documents core `make i18n-extract` and `make i18n-translate` with `root=` and `domain=team` (`ansible/roles/web-app-cst-team/README.md`).
  - `infinito-nexus/builder` asks for the shared stack in its own requirement (`docs/requirements/001-builder.md`).
  - `kevinveenbirkenbach/cosmos` and `infinito-nexus/quality` translate nothing yet.

## Decisions

1. **One stack per machine.** The tools (LibreTranslate, LiteLLM, Ollama and the `web-svc-translate` gateway of [040](040-translation-gateway.md)) run once per machine in the infra runner (stack `infinito-infra`), deployed through the infra inventory, started on demand by the i18n targets and stopped after `INFINITO_TOOLS_IDLE_GRACE`, exactly as [092](092-local-stack-architecture.md) Phase 6 and its D15 state. No checkout runs a tools service of its own.
2. **One interface for every repository.** A repository keeps its English source in `<root>/locale/<domain>.yml` and its catalogs in `<root>/locale/<code>/LC_MESSAGES/<domain>.po`, every message under the `msgctxt` `<domain>:<key>`. It extracts with core `make i18n-extract root=<repo> domain=<d>` and translates with core `make i18n-translate root=<repo> domain=<d> gateway=<url>`. The languages are those of core's `meta/languages.yml` ([054](054-gettext-catalogs-libretranslate.md)).
3. **The gateway is used, never deployed, by a caller.** `gateway=<url>` names the gateway of the shared stack; a run against it neither deploys nor redeploys a bundle and stops when the gateway names no language.
4. **Deferral.** Until the stack is up, no machine translation runs anywhere: no `make i18n-translate`, `make i18n-tune` or `make i18n-retry`, and no translation call of a repository's own. `make i18n-extract` needs no engine and stays allowed.
5. **Retirements in their own lines.** The store's own LibreTranslate container and the security check's runtime calls move onto the gateway in their own repository lines, not in core's branch.
6. **Order.** The static work (interface, idle bookkeeping, this document) lands first without Docker; the bring-up follows the IAM quality gate.
7. **Infra network.** One fixed /24 outside `172.30.0.0/16`, declared once in `default.env` as `INFINITO_INFRA_SUBNET` and checked against every network the repository declares; the tools ports are published on `127.0.0.1` only ([092](092-local-stack-architecture.md) D30).
8. **Visible checkouts.** `make infra-up` mounts exactly the roots of `INFINITO_WORKTREE_ROOTS`, each at its host path, through a generated compose override (092 D31).
9. **One migration.** The caches move into `infinito-infra` first (092 Phase 5) and the tools follow on top of them (092 D32).
10. **Reach by name.** Stacks and the test runner join the infra network and reach the tools by name, never through a host port (092 D33).
11. **Gateway only on loopback.** The runner publishes only the `web-svc-translate` port on `127.0.0.1`; LibreTranslate and LiteLLM stay internal to the infra network, so every repository translates through the gateway.
12. **Idle timer inside the runner.** The runner image carries the toolchain Python and sees the primary checkout read-only at its host path, so the idle stop is a systemd service and timer inside the runner (fewer moving parts than a sidecar with the host Docker socket). `make infra-up` writes both units below the cache base and links and enables them inside the runner; the host gets no unit. The service runs `utils.inventory.tools_idle stop-if-idle` with `cli.administration.infra tools-inside stop`, which stops only the tools projects and leaves the caches running.
13. **One compose helper.** Every compose call for the infra stack and for the role stacks inside it is built in `cli/administration/deploy/development/stack.py` (`infra_compose_argv`, `runner_compose_argv`) and reached through the `make infra-*`, `i18n-pause` and `i18n-resume` targets.
14. **One switch.** The cache cut-over of [092](092-local-stack-architecture.md) Phase 5 lands as one change together with the bring-up: `make infra-up` deploys the cache roles inside the runner before any stack is pointed at it, and no state exists in which the cache addresses name a runner that does not serve them yet. One key, `INFINITO_INFRA_RUNNER_CONTAINER`, names the runner for every consumer, the agent orchestrator's load reading included.

## Acceptance Criteria

### Core root and domain interface

- [x] `make i18n-extract root=<dir> domain=<name>` writes `<dir>/locale/<code>/LC_MESSAGES/<name>.po` for every non-English language of `meta/languages.yml` from `<dir>/locale/<name>.yml`, every message under `<name>:<key>`, and leaves core's catalogs untouched (`TestRoot` in `tests/unit/python/cli/build/i18n/test_main.py`, `TestKeyedMessages` in `tests/unit/python/utils/i18n/test_extract.py`).
- [x] `make i18n-translate root=<dir> domain=<name>` fills only that root's catalogs, and a run without `root` leaves them alone (`test_translate_fills_the_role_catalog_and_not_core` and `test_translate_without_a_root_leaves_the_role_catalog_alone` in `test_main.py`).
- [x] A `root` without a `domain`, a domain outside lowercase letters, digits and dashes (`../core` as the negative control), a `root` that is no directory, and a domain other than `core` or `docs` without `root` are refused before any work (`TestScope` in `test_main.py`).
- [x] `gateway=<url>` uses that gateway as it is: no deploy, no redeploy, and a gateway that names no language stops the run (`TestSharedGateway` in `tests/unit/python/utils/i18n/test_gateway.py`).
- [x] The `i18n_catalogue` lookup reads a role's own catalogs with `catalogs=<dir>` and core's without it (`tests/unit/python/plugins/lookup/test_i18n_catalogue.py`, `TestKeyedCatalogue` in `tests/unit/python/utils/i18n/test_keyed.py`).
- [x] A catalog outside core carries a header that defers to the licence of its repository, and a core catalog keeps core's licence (`TestRenderHeader` in `tests/unit/python/utils/i18n/test_catalog.py`).

### Tools in the infra runner

- [ ] Every criterion of [092](092-local-stack-architecture.md) Phase 5 (infra runner with the cache roles) is ticked; it is the host of this stack.
- [ ] Every criterion of [092](092-local-stack-architecture.md) Phase 6 (tools in the infra runner) is ticked.
- [x] `make dotenv` writes `INFINITO_TOOLS_IDLE_GRACE=2h` and `INFINITO_TOOLS_STAMP_DIR` below the cache base unless the environment sets them (`tests/unit/python/utils/env/handlers/infinito/test_tools_idle.py`, with an exported value as the negative control).
- [x] Every run through the gateway, shared or own, is stamped as running while it runs and stamps its end, and a run refused before it starts stamps nothing (`tests/unit/python/utils/i18n/test_gateway.py`).
- [x] `make i18n-tune` stamps its run through the engine's `server()` like `make i18n-translate`, and a run refused for a running deploy stamps nothing (`test_a_requested_redeploy_replaces_the_gateway_that_answers` and `test_a_refused_run_is_not_stamped` in `tests/unit/python/utils/i18n/test_libretranslate.py`).
- [x] `make test-oracle` runs its lane bring-up and its suite each as a stamped run through `python -m utils.inventory.tools_idle run -- <command>`, which holds the run while the command runs and passes its exit status through (`TestMain` in `tests/unit/python/utils/inventory/test_tools_idle_grace.py`).
- [x] The stop decision runs the stop only when no run is live and the grace has passed since the last stamped start or end: a run inside the grace and a live run keep the tools, a dead run's marker does not, an overridden grace moves the threshold, the stop holds the lock a starting run waits on, and a check waits for a run that is still registering instead of reaping its marker, with the unlocked check as the negative control (`tests/unit/python/utils/inventory/test_tools_idle_grace.py`).
- [x] `python -m utils.inventory.tools_idle stop-if-idle -- <stop command>` is the entry point the idle timer calls: it runs the stop command only past the grace and refuses a malformed grace (`TestMain` in `test_tools_idle_grace.py`).
- [ ] A timer inside the infra runner calls `stop-if-idle` with the stop of the tools services as its stop command. `[host]`
- [ ] `make infra-status` prints the gateway URL that `gateway=` takes, and every checkout of the machine reaches the same gateway at it. `[host]`

### Deferral and bring-up

- [ ] After the IAM quality gate, `make i18n-translate root=<team checkout>/ansible/roles/web-app-cst-team domain=team gateway=<url>` fills the team catalogs through the shared stack, and a run from a second checkout against the same URL starts no second tools service. `[host]`
- [ ] The operator newsletter that lifts the deferral names the gateway URL and the make targets, and goes out only after the bring-up criterion above is ticked.

### Consumers

Each box is ticked in its own repository line.

- [x] core: the `core` and `docs` domains translate through the shared stack, and no checkout layers a `tools` service. (`tests/unit/python/utils/i18n/test_libretranslate.py` `TestDeployGoesThroughTheInfraRunner`; `tests/unit/python/cli/administration/deploy/development/test_env_compose_file_args.py`)
- [ ] team: `web-app-cst-team` translates `locale/team.yml` through core `make i18n-translate root=<team role> domain=team gateway=<url>` and renders through `lookup('i18n_catalogue', 'team', ..., catalogs=<team role>)`.
- [ ] builder: the site's strings live in `locale/<domain>.yml` with catalogs per language and translate through the shared stack.
- [ ] cosmos: its interface strings live in `locale/<domain>.yml` with catalogs per language and translate through the shared stack.
- [ ] quality: its interface strings live in `locale/<domain>.yml` with catalogs per language and translate through the shared stack.
- [ ] gui and store: the own LibreTranslate container, its compose file and the LibreTranslate path of the i18n script and workflow are gone; the catalogs translate through the shared stack.
- [ ] security: the runtime translation calls go to the `web-svc-translate` gateway instead of `web-svc-libretranslate`, and any static strings translate through the shared stack.

### Documentation

- [x] The [web-svc-translate README](../../roles/web-svc-translate/README.md) states that `make i18n-translate` goes through the gateway, names `root`, `domain` and `gateway` with the source and catalog paths, and names the stamp directory and the idle grace.
- [ ] After the bring-up, the [cheatsheet](../contributing/tools/agents/cheatsheet.md) names the gateway URL and the three make parameters every repository passes.

## Cross-linking

- Related: [040 - Translation Gateway](040-translation-gateway.md), [054 - Gettext Catalogs with LibreTranslate Autotranslation](054-gettext-catalogs-libretranslate.md), [092 - Local Stack Architecture](092-local-stack-architecture.md), [039 - Core i18n Consumers](039-core-i18n-consumers.md).
- Implementing PR: to be added.
