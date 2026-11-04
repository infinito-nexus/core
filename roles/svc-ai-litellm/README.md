# LiteLLM Gateway

## Description

[LiteLLM](https://docs.litellm.ai/) is an LLM gateway that exposes an OpenAI-compatible HTTP API and forwards each request to a configured model backend, local or hosted. Clients authenticate with virtual API keys that the gateway issues and stores in its own database.

## Overview

This role deploys LiteLLM as a shared gateway container in Compose and Swarm deployments, backed by the central PostgreSQL service. The gateway is headless: it binds its HTTP port on the container host and claims no domain of its own, and the browser-facing surface is published separately by the LiteLLM Admin UI. It renders the model list from the interchangeable local backends available on the host, Ollama and LM Studio, and adds the OpenAI, Anthropic and OpenRouter entries whose API key is configured. Once the gateway is up, it provisions one virtual key per consuming application through the gateway admin API.

## Features

- **OpenAI-compatible API:** One HTTP endpoint serves every model listed in the gateway configuration.
- **Backend routing:** Model entries are generated for Ollama and LM Studio when those services run on the host, under the shared alias each model carries so a consumer names one model whichever local backend answers it.
- **Remote providers:** OpenAI, Anthropic and OpenRouter each add their models when a key is configured. The keys are declared in `meta/secrets.yml` with the `type` and `regex` their value must satisfy, and default to the central `API.<provider>.api_key` entry; an unset key leaves that provider's routes unpublished.
- **Configurable remote models:** The published remote models are the `litellm.remote_models` list in `meta/services.yml`, each entry an `alias`, the LiteLLM `model` string and its `provider`, plus an optional `context` in tokens and an optional `max_output_tokens` that becomes the route's `max_tokens` and aborts the deploy unless it is a positive integer. A remote route without it sets no bound, so the client's own limit applies; the shared `services.litellm.max_output_tokens` bounds only the local Ollama and LM Studio routes. An inventory replaces the list through `applications.svc-ai-litellm.services.litellm.remote_models`, and a provider without a key slot aborts the deploy.
- **Declared context windows:** A model entry carrying `context` publishes it as `model_info.max_input_tokens`, and an Ollama entry also runs with that window as `num_ctx` instead of the server's default, so a caller's prompt is not silently truncated.
- **Per-consumer virtual keys:** Each consuming application receives its own virtual key, created through the gateway admin API under an alias naming that application.
- **File-based model list:** The model list is mounted as a read-only config file, with database-stored model entries turned off.
- **Managed credentials:** The gateway master key and the admin UI password are generated and kept as role credentials, and the admin UI username is the platform administrator name.

## Provider validation during setup

### Optional FreeLLMAPI upstream

Select both `svc-ai-freellmapi` and `svc-ai-litellm` on the same Compose host.
LiteLLM remains the client gateway: clients retain their existing URL and
per-consumer virtual keys. The role automatically publishes `freellmapi/auto`,
forwarding to FreeLLMAPI's internal `/v1` endpoint with its own unified key.
LiteLLM deploys after FreeLLMAPI. No gateway flavor switch is required.

The FreeLLMAPI role reads the unified key its dashboard issued and persists it
in the token store for `platform_administrator`; LiteLLM resolves it from there.
The key never enters the inventory. If the store holds no key, setup fails and
asks for a FreeLLMAPI deploy first. Configure the provider pool before the
combined deploy, because the protocol checks need a working upstream.
Provider credentials can remain in FreeLLMAPI's existing
declarative `services.freellmapi.startup_config`; references to central inventory
secrets avoid duplicating the credential values.

By default the alias is selectable explicitly but excluded from LiteLLM's
general `auto` routing. To opt in, configure the guaranteed capabilities of
every model FreeLLMAPI may select, for example:

```yaml
applications:
  svc-ai-litellm:
    services:
      litellm:
        freellmapi:
          include_in_auto: true
          context: 32768
          traits:
            tools: true
```

Use these values only if the configured pool supports them. The settings
`freellmapi.alias` and `freellmapi.model` select the public alias and upstream
model ID; their initial values are `freellmapi/auto` and `auto`.
This pool is always classified as remote, even though its gateway container
runs locally. The existing `router.remote_fallback` and privacy rules still
apply. Dynamic pools are excluded from speed measurement because successive
requests may use different models. Do not configure FreeLLMAPI to route back
to this LiteLLM instance: that would create a forwarding cycle.

Setup also sends streaming requests and tool-call/result round trips through
LiteLLM for Chat Completions, Messages and Responses. These six checks run with
the configured validation worker limit and add nine inference requests to the
ordinary provider and consumer checks. Errors, missing answer text and
unfinished streams fail deployment; sanitized results contain no keys or
model text. The checks consume provider quota and may incur charges.
Live compatibility depends on the installed FreeLLMAPI version and configured
provider pool; the role remains pre-alpha until its full deploy loop is proven.

Remote declarations may set an explicit `api_base`. Such entries must also set
`traits.local` to a boolean: a remote URL must not be inferred to be a local
backend just because it has an explicit endpoint.

For OpenRouter's own router IDs, use the OpenAI-compatible transport:

```yaml
- alias: openrouter/free
  model: openai/openrouter/free
  provider: openrouter
  api_base: https://openrouter.ai/api/v1 # nocheck: url
  traits:
    local: false
```

LiteLLM 1.77.7 resolves the provider before translating Messages requests and
again before making the completion. Its provider resolver strips a matching
prefix on each pass, so `openrouter/openrouter/free` loses part of the upstream
model ID. Using the OpenAI transport preserves `openrouter/free` across both
passes. `provider: openrouter` still selects `OPENROUTER_API_KEY`, and the
explicit endpoint sends the request to OpenRouter. The provider validation uses
the same endpoint as the rendered route. The client-facing alias is unchanged.

`tasks/utils/validate/providers.yml` validates every declared remote model whose provider
has a configured key, after the gateway container starts and before consumers
are provisioned. It reads the actual provider key from that container and sends
a direct provider request through the installed LiteLLM SDK, without the gateway
router or its fallbacks. Missing keys, authentication failures, insufficient
credit, denied access, unavailable models and rate limits fail the deploy.
Providers without keys and mock models are excluded.

Each check requires a nonempty text answer and requests at most
`services.litellm.validation.max_output_tokens` (512) output tokens. This allows
reasoning models to produce visible text after their internal reasoning and
can incur an API charge. Provider checks run concurrently in isolated Python
processes, keeping each SDK's redirected output and logging independent.
It uses `services.litellm.upstream_timeout` and does not retry failed requests.
Logs contain provider/model labels, HTTP status and a sanitized diagnostic;
credentials and raw provider errors are never printed. A successful check proves
that the key can make that model request at deploy time, not that future quota,
availability or a large Claude conversation will fit. Subscription billing is
separate and is not validated by these tasks.

`services.litellm.validation.enabled: false` skips the provider, consumer and
FreeLLMAPI checks and the chat-model warm-up, so a deploy completes while
models do not answer. The gateway then publishes routes no deploy has proven.

## Consumer validation during setup

After provisioning consumer keys and warming the initial model,
`tasks/utils/validate/consumers.yml` validates every registered consumer's own
key against `/v1/models`, `/v1/chat/completions` and `/v1/messages`. Both inference
formats are checked for each published chat-model alias, including enabled local
backends and configured remote providers. Embedding aliases are excluded. With
no chat models configured, authentication is still tested and the result marks
inference as skipped. The automatic router alias is not added as a model probe.

The checks use the real virtual keys, so they also detect gateway permissions,
revoked keys, key budgets and translation failures that a direct provider check
cannot detect. Every inference must return nonempty answer text in the expected
protocol format without an error payload; an HTTP 200 or reasoning-only response
is insufficient. Each inference uses the same configured output-token budget;
the number of
requests is two per consumer and chat model, plus a Responses API request to
`/v1/responses` for each Codex model. Remote requests can incur API
charges. `services.litellm.consumer_validation` configures bounded retries:
`retries: 2`, `delay: 60` seconds and `max_delay: 120` seconds per wait. HTTP 429
and adapter-wrapped HTTP 5xx responses explicitly reporting a rate limit or
cooldown are retried. The validator honors numeric and HTTP-date `Retry-After`
headers, waits at least the configured delay, and fails without an early retry
when the requested wait exceeds `max_delay`. Recognized daily-quota exhaustion,
authentication, credit and other permanent errors are not retried. Exhausted
retries still fail deployment. Each result records attempts and seconds waited.
Provider daily quotas remain shared across consumers; repeatedly redeploying a
free model consumes that quota even when gateway keys are valid.

`services.litellm.validation.workers` bounds concurrency to three requests by
default. Authentication runs first; inference jobs for authenticated consumers
then run in a thread pool. Results retain declaration order, and failures are
reported after all jobs finish. Set workers to `1` for sequential checks.
Concurrency does not increase provider quotas or reduce the number of probes.

Keys travel on standard input in an unconditionally masked task. A following
assertion exposes only sanitized results (consumer/model/endpoint, HTTP status,
fixed error categories) and fails the deploy on any rejection. No key, response
text or raw exception is logged. These checks prove gateway access, not that a
running editor session has reloaded its connection configuration.
