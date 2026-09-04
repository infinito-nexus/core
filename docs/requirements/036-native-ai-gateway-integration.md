# 036 - Native AI Gateway Integration

## User Story

As an operator of a self-hosted deployment, I want every role whose application ships a native AI feature to reach the platform's own LiteLLM gateway instead of a third-party provider, so that prompts, documents and telemetry never leave the deployment and one credential rotation covers every application.

## Context

`svc-ai-litellm` already serves an OpenAI-compatible gateway, and `web-app-nextcloud` already binds its `integration_openai` app to that gateway through `tasks/addons/integration_openai.yml`, a `credentials.litellm_api_key` entry and a dedicated Playwright spec. That pattern is implemented once and is not required, described or verified for any other role.

A sweep over all 85 application roles for provider references (`openai`, `ollama`, `llm`, `anthropic`, `aiprovider`) in `meta/`, `vars/` and `templates/` returns only `dashboard`, `flowise`, `hermes`, `litellm`, `matrix`, `minio`, `nextcloud`, `openclaw` and `openwebui`. Everything below the AI-native roles is therefore unwired today.

Confirmed against upstream documentation, each accepting a custom OpenAI-compatible base URL:

| Role | Native surface | Endpoint |
| --- | --- | --- |
| `web-app-nextcloud` | Assistant via `integration_openai` | service URL plus API key |
| `web-app-mattermost` | Agents plugin | "OpenAI Compatible" service with API URL; a non-empty key is mandatory even when the upstream ignores it |
| `web-app-moodle` | AI subsystem provider | core `aiprovider_openai`; each action carries its own `action_<name>_endpoint`, so the pinned 4.5 branch needs no third-party provider plugin (`aiprovider_openaicompatible` requires Moodle 5.0) |
| `web-app-discourse` | Discourse AI | custom LLM; the host must be listed in `DISCOURSE_ALLOWED_INTERNAL_HOSTS` |
| `web-app-zammad` | Smart Assist | settings `ai_provider` (boolean "a provider is configured") plus `ai_provider_config` (`provider: custom_open_ai`, `url`, `model`, optional `token`). Needs 7.1.2; `stable-6.5` declares neither setting. `Setting.set` runs `AI::Provider::CustomOpenAI.ping!`, so writing the config is itself a reachability proof |
| `web-app-matrix` | ChatGPT bridge | bridge configuration; see the credential defect below |
| `web-app-wordpress` | plugin-provided, no core surface | a connector plugin such as AI Engine exposes a custom OpenAI-compatible endpoint |
| `web-app-n8n` | AI Agent nodes | a stored `openAiApi` credential carries `url` plus `apiKey`. The built-in assistant is out of reach: 1.95.3 exposes only `N8N_AI_ASSISTANT_BASE_URL`, which expects n8n's own assistant service rather than an OpenAI-compatible endpoint, and no `N8N_INSTANCE_AI_MODEL_URL` exists in that release |
| `web-app-mediawiki` | `AIEditingAssistant` extension | provider `open-ai`; `$wgAIEditingAssistantActiveProviderConnection` carries `url`, `endpoint`, `model` and `secret`. Hard-requires `VisualEditorPlus`, which is not bundled |
| `web-app-xwiki` | AI LLM Application extension | the role installs the extension and points its OpenAI-compatible provider at the gateway in `tasks/addons/ai-llm.yml` |

`web-app-matrix` is the one role that already ships an AI credential and points it at the vendor: `meta/secrets.yml` declares `chatgpt_bridge_openai_api_key` with the validation `^sk-[a-zA-Z0-9]{40,}$`. That pattern enforces OpenAI's own key format and therefore **rejects a LiteLLM virtual key by construction**, so the schema has to change before the bridge can reach the gateway at all.

`web-app-wordpress` has no AI surface in core; the requirement applies to whichever connector plugin the role installs, and the role MUST pin one rather than leaving the choice to a site administrator. The pinned connector is `ai-engine`, whose `custom` engine type takes an OpenAI-compatible base URL and an API key per environment.

`web-app-zammad` was pinned at 6.5.0, which ships no AI surface at all. The role is bumped to 7.1.2, the newest line whose contract is still the `ai_provider` / `ai_provider_config` setting pair; past 7.1.x the provider moves into an `AI::ProviderConnection` record and the contract changes. 7.1.2 accepts Elasticsearch `>= 7.8, < 10`, so the role's existing 8.13.4 pin stands.

The three candidates that vendor documentation claimed were probed against running instances on 2026-08-27, and each is filed below on what the deployed artefact actually offers rather than on the claim:

| Role | Measured at | Finding | Disposition |
| --- | --- | --- | --- |
| `web-app-baserow` | 2.3.3 | `settings.BASEROW_OPENAI_BASE_URL` reaches the OpenAI client at `backend/src/baserow/core/generative_ai/generative_ai_model_types.py:288`, but the only two surfaces that ever send a prompt live in `baserow_premium` and both open with `LicenseHandler.raise_if_user_doesnt_have_feature(PREMIUM, request.user, workspace)`: `AsyncGenerateAIFieldValuesView` and `GenerateFormulaWithAIView` (`premium/backend/src/baserow_premium/api/fields/views.py`). An unlicensed deployment configures the endpoint and can never reach it | excluded |
| `web-app-homeassistant` | 2026.7 | `openai_conversation/config_flow.py` contains no `base_url` (0 matches), so the OpenAI agent cannot be pointed anywhere but the vendor. The only configurable local path is the separate `ollama` integration, whose `config_flow.py` carries `CONF_URL` (7 matches) but speaks Ollama's native API rather than the gateway's OpenAI-compatible surface | excluded |
| `web-app-xwiki` | `lts-postgres-tomcat` | no AI or LLM extension is present in `data/extension/repository` on the pinned image, so there is no AI surface to point at the gateway until the XWiki AI LLM Application extension is installed by the role | confirmed, the role installs the extension in `tasks/addons/ai-llm.yml` |

`web-app-baserow` is the one row measured against the pinned source rather than a running instance. Confirm it on the deployed stack with `POST /api/database/fields/<field_id>/generate-ai-field-values/` as the seeded superuser: an unlicensed instance answers HTTP 402.

Excluded, with the reason recorded so the question is not reopened:

| Role | Reason |
| --- | --- |
| `web-app-baserow` | the endpoint is configurable but both prompt-sending views are premium-licence gated; see the measurement above |
| `web-app-homeassistant` | the OpenAI agent takes no base URL and the `ollama` integration speaks Ollama's native API; see the measurement above |
| `web-app-gitlab` | Duo is bound to the vendor service and exposes no self-hosted endpoint |
| `web-app-odoo` | version 19 hardcodes a vendor model for AI server actions; a configurable endpoint needs third-party modules |
| `web-app-erpnext` | no AI surface in the core; every option is a separately installed app |
| `web-app-jira`, `web-app-confluence` | Atlassian Intelligence is vendor-hosted |
| `web-app-magento`, `web-app-shopware` | the shipped assistants are vendor services; only third-party modules expose an endpoint |
| `web-app-openproject` | no AI surface found in the product |
| `web-app-espocrm` | measured at tag 10.0.4: zero tree paths match `AI`/`Intelligence`/`OpenAI`/`LLM`/`GPT`/`prompt` while 116 match `Mail` on the same payload, so the search was live. The AI features live only in the closed-source Intelligence extension, which needs a purchased licence and is published in no `espocrm` repository. A version bump does not help: upstream documents the extension as requiring 10.0.3 or greater, so newer cores host it rather than absorb it |
| `web-app-peertube` | measured at tag v8.2.4 across three independent surfaces: `config/production.yaml.example` `video_transcription:` carries only `enabled`/`engine`/`engine_path`/`model`/`model_path`/`timeout`/`remote_runners.enabled`; `support/docker/production/config/custom-environment-variables.yaml` exposes exactly the seven matching `PEERTUBE_VIDEO_TRANSCRIPTION_*` variables, none of them a URL or a key; `server/core/initializers/config.ts` agrees. Transcription is local Whisper, not an OpenAI-compatible endpoint |
| infrastructure and static roles | `checkmk`, `prometheus`, `matomo`, `seaweedfs`, `minio`, `mailu`, `keycloak`, `lam`, `fusiondirectory`, `phpldapadmin`, `phpmyadmin`, `pgadmin`, `pihole`, `semaphore`, `jenkins`, `gitea`, `hugo`, `sphinx`, `yourls`, `mini-qr`, `littlejs`, `chess`, `roulette-wheel`, `navigator`, `mig`, `dashboard`, `fediwall`, `postmarks` carry no AI surface |
| fediverse and media roles | `mastodon`, `pixelfed`, `friendica`, `socialhome`, `bookwyrm`, `mobilizon`, `funkwhale`, `bluesky`, `bridgy-fed`, `jellyfin` ship no configurable AI surface |
| remaining application roles | `akaunting`, `decidim`, `fider`, `listmonk`, `pretix`, `snipe-it`, `taiga`, `penpot`, `joomla`, `suitecrm`, `kix`, `opencloud`, `opentalk`, `jitsi`, `bigbluebutton`, `erpnext` show no first-party AI surface with a configurable endpoint; revisit when upstream adds one |

## Acceptance Criteria

- [ ] Each unverified candidate is probed against a running instance and moved into the confirmed table or the exclusion table with its reason, so the scope rests on measurement rather than vendor claims.
- [x] Every role in the confirmed table declares its native AI surface in `meta/services.yml` with `enabled` and `shared` bound to `'svc-ai-litellm' in group_names`, so a deployment without the gateway configures no AI surface at all.
- [x] Every role in the confirmed table carries a `credentials.litellm_api_key` entry in `meta/secrets.yml`, and the deploy writes that virtual key into the application's own AI configuration rather than a shared or hardcoded key.
- [x] Every role in the confirmed table points its AI base URL at the in-cluster gateway address, and a deploy-time assertion fails when the configured URL resolves outside the deployment.
- [x] No role in the confirmed table retains a default that sends requests to a third-party provider when the gateway is enabled.
- [x] A Playwright spec per role proves the configured surface answers a prompt through the gateway, mirroring `roles/web-app-nextcloud/files/playwright/addons/integration_openai.spec.js`.
- [x] The deploy fails when a role declares the AI surface enabled while its configuration still carries an empty or unresolved API key, so a silently unauthenticated surface cannot reach a green deploy.
- [x] No credential validation in `meta/secrets.yml` encodes a vendor key format, so a gateway-issued virtual key satisfies every AI credential the platform mints.
- [x] `docs/requirements/027-integration-matrix.md` lists the AI surface of every role in the confirmed table.

Consumers that must name a model (`web-app-moodle`, `web-app-matrix`) read `LITELLM_CHAT_MODEL`, which picks the first non-embedding preload model of `svc-ai-ollama` and mirrors the branch order of the gateway's own `config.yaml.j2`. The consumer resolves that branch from `lookup('deployment').groups`, the round's deployed closure, which is what `group_names` carries. `.running` is wrong here: a targeted `apps=` round sets it to the whitelist, and `svc-ai-ollama` is pulled in as a dependency rather than named on the command line, so both backend branches fall through to the `openrouter/auto` vendor default. The gateway then answers `Invalid model name passed in model=openrouter/auto` with HTTP 400 and no consumer can complete a prompt. On a multi-host round where the gateway and a backend land on different hosts they can diverge, and the gateway's host-scoped backend selection is what has to change; that belongs to [031](031-llm-gateway-model-backends.md).

### Which variant exercises the gateway

`svc-ai-litellm` pulls `svc-ai-ollama` and `svc-ai-lmstudio` with it, so a consumer that enables the gateway adds roughly 6 GB to its round. Variant 0 is the fallback every higher round lands on, so a heavy shared dependency pinned there appears in every round: with the gateway on variant 0 of `web-app-matrix`, `web-app-mattermost` and `web-app-zammad`, the `web-app-nextcloud` rounds that pin those partners exceed the 64 GB budget guarded by `tests/integration/roles/meta/variants/test_resource_budget.py`.

The gateway is therefore pinned on **variant 2** for every consumer that ships three variants, and left on variant 0 for the two-variant roles, whose round 2 falls back to it. One `make compose-deploy variant=2` run exercises eight of the nine confirmed roles. `web-app-nextcloud` is the exception: its AI surface has always lived on its own variant 7, alongside the other bridged partners it distributes across budget bins.

## See Also

- [031 - LLM Gateway Model Backends](031-llm-gateway-model-backends.md)
- [025 - MCP Role Integration](025-mcp-role-integration.md)
