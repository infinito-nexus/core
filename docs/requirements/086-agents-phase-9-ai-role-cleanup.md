# 086 - Agents Phase 9: AI Role Cleanup and Requirement Hygiene

## User Story

As an operator, I want the AI roles to run one LibreTranslate engine, consume the translation gateway, enable their optional Open WebUI services and test peer presence through services lookups, and I want the earlier AI requirements to agree with the agents restructuring, so that the platform and its requirements carry no duplicate or contradicting statement before the board migration.

## Scope

- Phase 9 of [089 - Agents and AI Restructuring](089-agents-restructuring.md). The Role cleanup and Superseded Criteria sections of 089 apply.
- The criteria below are moved from 089 unchanged: "this file" and "listed above" in them mean 089 and its Superseded Criteria table.
- Builds on: `roles/svc-ai-libretranslate-engine`, `roles/web-svc-libretranslate`, `roles/web-svc-translate`, `roles/web-app-mediawiki`, `roles/web-app-openwebui`, `roles/svc-ai-robot` and the requirement files 032 to 040 and 050 to 058.
- Gate: the touched roles deploy with their Playwright specs green, and the requirement lints are green.
- Depends on: no other phase; it MAY be implemented in parallel to any phase before [088](088-agents-phase-11-ci-and-acceptance.md).

## Acceptance Criteria

### Role cleanup

- [ ] Only `svc-ai-libretranslate-engine` runs a LibreTranslate container; `web-svc-libretranslate` starts none and `prefetch_models.py` exists once.
- [ ] `web-app-mediawiki` consumes `web-svc-translate`, and translation through it works in a Playwright spec.
- [x] `web-svc-translate` uses `libretranslate-engine` consistently in its README, `router.order` and consumer key.
- [ ] `web-app-openwebui` enables tika, searxng and jupyter, and Playwright specs cover a RAG upload, a web search and a code execution.
- [x] The `web-app-openwebui` description no longer names Ollama as its backend.
  - Evidence: `roles/web-app-openwebui/README.md` and the galaxy description in `roles/web-app-openwebui/meta/main.yml` name the `svc-ai-litellm` gateway; the role's model connections are the gateway and the agent broker only (`roles/web-app-openwebui/vars/main.yml`).
- [ ] `svc-ai-robot` reads its persona from `agents/roles/robot/`.
- [ ] A grep over the `tasks/`, `templates/` and `vars/` of the AI roles finds no `in group_names` peer-presence test; the service flags in `meta/services.yml` keep theirs.
- [x] `web-svc-translate` reads its router strategy without a code-level fallback value.
  - Evidence: `roles/web-svc-translate/files/python/translate_gateway/asgi.py` reads `TRANSLATE_ROUTER_STRATEGY` without a fallback, `roles/web-svc-translate/templates/env.j2` always renders it, and `roles/web-svc-translate/files/python/translate_gateway/router.py` refuses any value outside `system_one` and `preference`; `tests/unit/python/roles/web-svc-translate/files/translate_gateway/test_router.py` with its red fixture, recorded as `UT-TRANSLATE-STRATEGY` in `agents/criteria.yml`.

### Requirement hygiene

- [x] Every superseded criterion listed above carries a pointer to this file in its earlier requirement.
  - Evidence: a `Superseded by [089](089-agents-restructuring.md#superseded-criteria)` line next to every row of 089's Superseded Criteria table: 032 (agent count, both Flowise criteria), 037 (`agent-user` grant, hard-enabled runtimes and the `hermes`/`openclaw` models, the broker's own key and the `user` field, the `model` key), 035 (the `administrator` and `mcp` gate), 036 and 040 (peer presence), 038 (`router_strategy`), 050 (MCP facts, three places) and `docs/requirements/README.md` (requirements as work packages).
- [x] [050](050-mcp-role-integration.md) and [035](035-mcp-proxy-expansion.md) agree on one disposition per application, matching its `meta/mcp.yml`.
- [x] [035](035-mcp-proxy-expansion.md) names `dsk-*` roles, has no stray fragment, and lists the AI roles added since it was written.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
