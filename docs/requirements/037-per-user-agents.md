# 037 - Per-User Agents on Demand from Open WebUI

## User Story

As a platform user with agent access, I want Open WebUI to start my own Hermes or OpenClaw agent the first time I address it, isolated from every other user's agent, so that I work with a personal agent without an administrator provisioning one for me, while administrators decide through RBAC who may use agents at all.

## Scope

- A new role `svc-ai-agent-broker` runs the broker and a restricted container-API proxy.
- `web-app-hermes` and `web-app-openclaw` each gain the RBAC role `agent-user` and keep their existing shared instance unchanged.
- `web-app-openwebui` gains a second OpenAI connection pointing at the broker, forwards the caller's identity and restricts each agent model to its group.
- Compose and swarm are both supported.

## Design

### Request flow

1. Open WebUI sends `POST /v1/chat/completions` with `model: hermes` or `model: openclaw` to the broker, authenticated with the broker key and carrying the `X-OpenWebUI-User-*` headers (`ENABLE_FORWARD_USER_INFO_HEADERS=true`).
2. The broker rejects any request whose bearer is not the broker key, and any request without a user id header.
3. The broker resolves the caller's groups from Keycloak and refuses with HTTP 403 when the caller is not in the `agent-user` group of the requested platform.
4. The broker looks up the caller's agent for that platform by name. When none exists it creates one; when it is stopped it starts it; it then waits until the agent answers its health endpoint.
5. The broker forwards the request to the agent with the agent's own bearer key and streams the answer back unchanged.
6. `GET /v1/models` lists both platforms; Open WebUI shows each only to its group through model access grants.

### Model visibility

With the broker deployed, Open WebUI runs with `BYPASS_MODEL_ACCESS_CONTROL=false`. A deploy-time step grants every LiteLLM model public read access and each agent model read access for its `agent-user` group only. A `svc-ai-litellm` deploy repeats that step in a running Open WebUI, so a model added to the gateway is visible to every user without an Open WebUI deploy.

### Agent container

- One container (compose) or one single-replica service (swarm) per user and platform, named from the platform and a hash of the user id, labelled with owner and platform.
- Runtime is the isolating runtime selected by `svc-virt-kata`; the broker stops and refuses an agent that came up under `runc`.
- No privileged mode, no host network, pid, ipc or user namespace, no host bind mount, no container-engine socket.
- A dedicated volume per user and platform holds the agent's state; it survives a stop.
- A dedicated network per agent whose only other member is the broker.
- A random bearer key per agent, known only to the broker, used in both directions.
- The agent holds no model credential: it calls `http://agent-broker:<port>/llm/v1`, and the broker relays the call to LiteLLM with the broker's own virtual key and the owner in the OpenAI `user` field, and logs a `relay` event with owner, platform, path and upstream status.
- CPU, memory and pids limits come from the platform role's `meta/services.yml`.

### Lifecycle

`svc-ai-agent-broker/meta/services.yml` carries under `agent-broker.agents`:

| Key | Meaning |
|---|---|
| `model` | model alias every agent is configured with; defaults to the gateway's chat model |
| `idle_stop` | `true` stops an agent after `idle_minutes` without a request; `false` keeps it running |
| `idle_minutes` | idle time before a stop |
| `max_running` | upper bound of concurrently running agents; a request beyond it gets HTTP 503 |
| `start_timeout` | seconds an agent gets to answer its health endpoint |
| `access_cache_seconds` | how long a Keycloak membership answer is reused |

A stopped agent is started again on the next request with its volume re-attached. An agent serving a request is never stopped, and the idle time is re-read under the agent's lock before the stop. When a caller has lost the `agent-user` group, the broker refuses the request and stops that caller's running agent.

### Context window

A model that serves agents declares its context window in tokens: `context` on an `AI_LOCAL_MODELS` entry or on a `services.litellm.remote_models` entry. LiteLLM sends it to Ollama as `num_ctx` and publishes it as `model_info.max_input_tokens`, and the broker writes it into the agent config as Hermes `model.context_length` and OpenClaw `contextWindow`. Without it Ollama truncates the agent's prompt to its own default window and the agents assume windows of their own.

### Container API

The broker reaches the container engine only through a filtered unix socket in a volume it shares with the socket proxy. The proxy serves no TCP port; in compose it also runs with `network_mode: none`, while a swarm task carries the stack's default overlay attachment. The proxy admits only the container, service, task, network, volume and image calls the broker makes, and refuses every other method and path, including exec and delete. The image, runtime, limits and mounts of an agent are fixed by the broker, never taken from the request.

The proxy filters methods and paths, not request bodies. `POST /volumes/create` stays on the allowlist because the broker creates a volume per agent, and a local-driver volume with `o=bind,device=/` is a host bind mount that arrives as a volume. Fields such as `Privileged`, `PidMode` or `CapAdd` on `containers/create` are likewise unfiltered. The isolation therefore holds against a compromised **agent**, which reaches no socket at all, not against a compromised **broker**.

## Acceptance Criteria

### Role and configuration

- [ ] `svc-ai-agent-broker` deploys in compose and swarm mode and passes the repository lint suite.
- [x] The `agent-broker.agents` keys reach the running broker from `meta/services.yml`, so an inventory override changes its behaviour.
- [x] The socket proxy refuses `POST /containers/{id}/exec`, a container or service create carrying a host bind mount, and `DELETE /containers/{id}`.
- [x] The socket proxy serves the engine on the unix socket shared with the broker and publishes no port; in compose it runs with `network_mode: none`.

### Access control

- [x] `web-app-hermes` and `web-app-openclaw` each declare the RBAC role `agent-user`, which provisions a Keycloak group.
- [x] Open WebUI lists `hermes` and `openclaw` only to a user in the matching group, while every LiteLLM model stays visible to all users.
- [x] A model added to LiteLLM becomes visible to all Open WebUI users after a `svc-ai-litellm` deploy alone.
- [x] A direct call to the broker for a user outside the group gets HTTP 403 and creates no container.
- [x] A request with a wrong or missing broker key gets HTTP 401.

### Agent lifecycle

- [x] The first prompt of an entitled user creates exactly one agent for that user and platform and returns the agent's answer in Open WebUI.
- [x] A second prompt from the same user reuses the same agent without restarting it.
- [x] A stopped agent is started again by the next prompt, keeps its container and its state.
- [x] With `idle_stop: true` the sweep stops an agent that has been idle for `idle_minutes`, and never one that is serving a request or was just used.
- [x] With `idle_stop: false` the sweep stops nothing.

### Isolation

- [x] Two users get two different containers, volumes, networks and bearer keys.
- [x] An agent inspected on the engine runs under the isolating runtime, not `runc`.
- [x] A file written by one user's agent is not visible to the other user's agent.
- [x] One agent cannot reach the other agent's network address.

### Tests

- [x] `web-app-openwebui` ships a Playwright spec that logs in as `biber` without `agent-user` and asserts that neither agent model is listed or answers, while every served gateway model is listed.
- [x] The same spec grants `biber` the `agent-user` groups, logs in again and asserts an answer from `hermes` and from `openclaw` through Open WebUI.
- [x] `svc-ai-agent-broker` ships a CLI test that proves the broker-key refusal, the RBAC refusal, two distinct agents under the isolating runtime, file isolation and network isolation on the engine.
- [x] The same CLI test proves from the broker's `relay` events that a `hermes` and an `openclaw` agent each got a model answer from LiteLLM, independent of what the model wrote.
- [x] Unit tests cover the idle sweep: it stops an idle agent, skips one that is serving a request or was just used, and does nothing while `idle_stop` is false.
