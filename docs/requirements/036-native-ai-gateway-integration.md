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
| `web-app-moodle` | AI subsystem provider | `aiprovider_openaicompatible` |
| `web-app-discourse` | Discourse AI | custom LLM; the host must be listed in `DISCOURSE_ALLOWED_INTERNAL_HOSTS` |
| `web-app-zammad` | Smart Assist, 7.0 and later | provider endpoint plus optional key |
| `web-app-matrix` | ChatGPT bridge | bridge configuration; see the credential defect below |
| `web-app-wordpress` | plugin-provided, no core surface | a connector plugin such as AI Engine exposes a custom OpenAI-compatible endpoint |
| `web-app-n8n` | AI Agent nodes plus the built-in assistant | an OpenAI credential carries a base URL; the assistant reads `N8N_INSTANCE_AI_MODEL_URL` |
| `web-app-mediawiki` | `AIEditingAssistant` extension | provider is selected per wiki, `open-ai` or `ollama` |
| `web-app-espocrm` | Intelligence add-on | provider list includes a custom OpenAI-compatible endpoint |
| `web-app-peertube` | transcription plugin | Whisper, served locally or through an OpenAI-compatible endpoint |

`web-app-matrix` is the one role that already ships an AI credential and points it at the vendor: `meta/schema.yml` declares `chatgpt_bridge_openai_api_key` with the validation `^sk-[a-zA-Z0-9]{40,}$`. That pattern enforces OpenAI's own key format and therefore **rejects a LiteLLM virtual key by construction**, so the schema has to change before the bridge can reach the gateway at all.

`web-app-wordpress` has no AI surface in core; the requirement applies to whichever connector plugin the role installs, and the role MUST pin one rather than leaving the choice to a site administrator.

Claimed by vendor documentation but not yet verified against a running instance, so each MUST be confirmed before it is implemented: `web-app-homeassistant` (conversation agent), `web-app-xwiki` (AI extension), `web-app-baserow` (AI field).

Excluded, with the reason recorded so the question is not reopened:

| Role | Reason |
| --- | --- |
| `web-app-gitlab` | Duo is bound to the vendor service and exposes no self-hosted endpoint |
| `web-app-odoo` | version 19 hardcodes a vendor model for AI server actions; a configurable endpoint needs third-party modules |
| `web-app-erpnext` | no AI surface in the core; every option is a separately installed app |
| `web-app-jira`, `web-app-confluence` | Atlassian Intelligence is vendor-hosted |
| `web-app-magento`, `web-app-shopware` | the shipped assistants are vendor services; only third-party modules expose an endpoint |
| `web-app-openproject` | no AI surface found in the product |
| infrastructure and static roles | `checkmk`, `prometheus`, `matomo`, `seaweedfs`, `minio`, `mailu`, `keycloak`, `lam`, `fusiondirectory`, `phpldapadmin`, `phpmyadmin`, `pgadmin`, `pihole`, `semaphore`, `jenkins`, `gitea`, `hugo`, `sphinx`, `yourls`, `mini-qr`, `littlejs`, `chess`, `roulette-wheel`, `navigator`, `mig`, `dashboard`, `fediwall`, `postmarks` carry no AI surface |
| fediverse and media roles | `mastodon`, `pixelfed`, `friendica`, `socialhome`, `bookwyrm`, `mobilizon`, `funkwhale`, `bluesky`, `bridgy-fed`, `jellyfin` ship no configurable AI surface |
| remaining application roles | `akaunting`, `decidim`, `fider`, `listmonk`, `pretix`, `snipe-it`, `taiga`, `penpot`, `joomla`, `suitecrm`, `kix`, `opencloud`, `opentalk`, `jitsi`, `bigbluebutton`, `erpnext` show no first-party AI surface with a configurable endpoint; revisit when upstream adds one |

## Acceptance Criteria

- [ ] Each unverified candidate is probed against a running instance and moved into the confirmed table or the exclusion table with its reason, so the scope rests on measurement rather than vendor claims.
- [ ] Every role in the confirmed table declares its native AI surface in `meta/services.yml` with `enabled` and `shared` bound to `'svc-ai-litellm' in group_names`, so a deployment without the gateway configures no AI surface at all.
- [ ] Every role in the confirmed table carries a `credentials.litellm_api_key` entry in `meta/schema.yml`, and the deploy writes that virtual key into the application's own AI configuration rather than a shared or hardcoded key.
- [ ] Every role in the confirmed table points its AI base URL at the in-cluster gateway address, and a deploy-time assertion fails when the configured URL resolves outside the deployment.
- [ ] No role in the confirmed table retains a default that sends requests to a third-party provider when the gateway is enabled.
- [ ] A Playwright spec per role proves the configured surface answers a prompt through the gateway, mirroring `roles/web-app-nextcloud/files/playwright/addons/integration_openai.spec.js`.
- [ ] The deploy fails when a role declares the AI surface enabled while its configuration still carries an empty or unresolved API key, so a silently unauthenticated surface cannot reach a green deploy.
- [ ] No credential validation in `meta/schema.yml` encodes a vendor key format, so a gateway-issued virtual key satisfies every AI credential the platform mints.
- [ ] `docs/requirements/027-integration-matrix.md` lists the AI surface of every role in the confirmed table.

## See Also

- [031 - LLM Gateway Model Backends](031-llm-gateway-model-backends.md)
- [025 - MCP Role Integration](025-mcp-role-integration.md)
