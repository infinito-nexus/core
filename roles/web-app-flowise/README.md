# Flowise

## Description

**Flowise** is a visual builder for AI workflows. Create, test, and publish chains that combine LLMs, your documents, tools, and vector search, without writing glue code.

## Overview

Users design flows on a drag-and-drop canvas (LLM, RAG, tools, webhooks), test them interactively, and publish endpoints that applications or bots can call. Flowise works well with local backends such as **Ollama** (directly or via **LiteLLM**) and **Qdrant** for retrieval.

## Features

- No/low-code canvas to build assistants and pipelines
- Publish flows as HTTP endpoints for easy integration
- Retrieval-augmented generation (RAG) with vector DBs (e.g., Qdrant)
- Pluggable model backends via OpenAI-compatible API or direct Ollama
- Keep data and prompts on your own infrastructure
- **MCP client contract:** With an MCP server deployed alongside it, the role declares the MCP client side of the platform contract as an internal streamable-HTTP client with a read-only tool policy. The deploy registers every discovered provider in the instance-level `/api/v1/custom-mcp-servers` registry under an `infinito:` name, stores the bearer as an encrypted `CUSTOM_HEADERS` `authConfig`, authorizes each entry and compares the discovered tools against the provider's declared allowlist. `CUSTOM_MCP_PROTOCOL=sse` pins the deployment to URL-based MCP servers, so no flow can spawn a local stdio command. Reaching an MCP server whose URL resolves inside the container network requires `HTTP_SECURITY_CHECK=false` plus an `HTTP_DENY_LIST` that keeps loopback and the cloud-metadata addresses denied; both are rendered only while MCP servers are discovered, and the deploy proves the list is live by pointing a throwaway entry at each denied address. One managed Agentflow fixture calls a single named tool with fixed arguments and is executed on every deploy. Wiring a provider into a flow of your own stays an operator step.

## Further Resources

- Flowise: [flowiseai.com](https://flowiseai.com)
- Qdrant: [qdrant.tech](https://qdrant.tech)
- LiteLLM: [litellm.ai](https://www.litellm.ai)
- Ollama: [ollama.com](https://ollama.com)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/M7hkFsuTnwiSqcnhNrreXT)

## MCP Client

Flowise consumes MCP through the *Custom MCP* tool node, which is configured
**inside a flow**. It exposes no instance-level registry API, so the role
prepares the instance and leaves the per-flow wiring to the operator.

### What the role does

| Property | Value |
| --- | --- |
| Direction | `client` |
| Transport | Streamable HTTP |
| `CUSTOM_MCP_PROTOCOL` | `sse`, so no flow can spawn a local stdio command |
| `HTTP_SECURITY_CHECK` | `false` while MCP servers are discovered |
| `HTTP_DENY_LIST` | loopback and cloud-metadata addresses stay denied |

Relaxing the security check is what lets a Custom MCP node reach a container
hostname such as `http://baserow:80/mcp`; the deny list keeps loopback and the
metadata endpoints unreachable.

### What the role does not do

It does not preregister servers and it ships no MCP Playwright spec, because
neither has an instance-level surface to act on. Selecting a server inside a flow
is a deliberate operator step.

### Default state

Off. `mcp.enabled` is false unless an MCP server role is part of the
deployment.

### How to disable

Remove the MCP server roles, or pin `mcp.enabled: false` for this role.
The security-check and deny-list overrides are then not rendered.

## Persona contract opt-outs

The shared `administrator` persona journey is opted out via `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`.
Flowise has no in-app OIDC adapter: SSO is an oauth2-proxy sidecar (`services.sso.flavor: oauth2`), and behind that gate Flowise still presents its own sign-in form for its single instance account `flowise-api-bot`, which `tasks/utils/owner.yml` registers.
The Keycloak administrator credential the persona types is not that account's, so the journey cannot reach an authenticated Flowise surface; the OIDC gate itself is covered by `files/playwright/test-oidc-login.js`.

`biber` runs in `files/playwright/test-biber-persona.js` while `sso` is enabled and is skipped with `SSO_SERVICE_ENABLED=false`.
Without a Flowise role group, the oauth2-proxy refuses `biber` with a 403 at `/oauth2/callback`, because `sso.oauth2.allowed_groups` in `meta/services.yml` admits only the `administrator` and `mcp` role groups.
In the `mcp` role group, `biber` passes the gate and lands on Flowise's own sign-in form: the role grants no Flowise account, so the app shell stays absent and `/api/v1/chatflows` answers 401.
The scenario joins `biber` to the group through the Keycloak Admin REST API and removes the membership afterwards.
