# LiteLLM Gateway

## Description

[LiteLLM](https://docs.litellm.ai/) is an LLM gateway that exposes an OpenAI-compatible HTTP API and forwards each request to a configured model backend, local or hosted. Clients authenticate with virtual API keys that the gateway issues and stores in its own database.

## Overview

This role deploys LiteLLM as a shared gateway container in Compose and Swarm deployments, backed by the central PostgreSQL service. The gateway is headless: it binds its HTTP port on the container host and claims no domain of its own, and the browser-facing surface is published separately by the LiteLLM Admin UI. It renders the model list from the interchangeable local backends available on the host, Ollama and LM Studio, and adds the OpenAI, Anthropic and OpenRouter entries whose API key is configured. Once the gateway is up, it provisions one virtual key per consuming application through the gateway admin API.

## Features

- **OpenAI-compatible API:** One HTTP endpoint serves every model listed in the gateway configuration.
- **Backend routing:** Model entries are generated for Ollama and LM Studio when those services run on the host, under the shared alias each model carries so a consumer names one model whichever local backend answers it.
- **Speech transcription:** while [svc-ai-speech](../svc-ai-speech/README.md) runs on the host, `/v1/audio/transcriptions` answers for its `services.speech.model_alias` (`whisper-1`) from that server, with the server's own `request_timeout`; without it the gateway publishes no audio route. The route declares `model_info.mode: audio_transcription`, so the router never picks it for a chat request and it does not count as a local chat route that would hold a request on the cluster, and it is left out of the speed measurement.
- **Speech synthesis:** while [svc-ai-speech](../svc-ai-speech/README.md) runs on the host, `/v1/audio/speech` answers for its `services.piper.model_alias` (`tts-1`) from that role's piper server at `PIPER_BASE_LOCAL_URL`, with the server's own `request_timeout`; without it the gateway publishes no synthesis route. The route declares `model_info.mode: audio_speech`, so the router never picks it for a chat request, and it is left out of the speed measurement like the transcription route.
- **Remote providers:** OpenAI, Anthropic and OpenRouter each add their models when a key is configured. The keys are declared in `meta/secrets.yml` with the `type` and `regex` their value must satisfy, and default to the central `API.<provider>.api_key` entry; an unset key leaves that provider's routes unpublished.
- **Configurable remote models:** The published remote models are the `litellm.remote_models` list in `meta/services.yml`, each entry an `alias`, the LiteLLM `model` string and its `provider`, plus an optional `context` in tokens and an optional `max_output_tokens` that becomes the route's `max_tokens` and aborts the deploy unless it is a positive integer. A remote route without it sets no bound, so the client's own limit applies; the shared `services.litellm.max_output_tokens` bounds only the local Ollama and LM Studio routes. An inventory replaces the list through `applications.svc-ai-litellm.services.litellm.remote_models`, and a provider without a key slot aborts the deploy.
- **Declared context windows:** A model entry carrying `context` publishes it as `model_info.max_input_tokens`, and an Ollama entry also runs with that window as `num_ctx` instead of the server's default, so a caller's prompt is not silently truncated.
- **Per-consumer virtual keys:** Each consuming application receives its own virtual key, created through the gateway admin API under an alias naming that application.
- **Consumer contract:** [tasks/utils/consumer_contract.yml](tasks/utils/consumer_contract.yml) refuses a consumer with an empty virtual key or a gateway URL that leaves the deployment. The svc-stack back unit [tasks/batch/back.yml](../svc-stack/tasks/batch/back.yml) runs it right before the backend of every stack consumer that enables `services.litellm`; a consumer without a stack backend includes it itself.
- **File-based model list:** The model list is mounted as a read-only config file, with database-stored model entries turned off.
- **No stored prompts:** The spend logs keep each request's usage and cost but never its prompt or reply (`store_prompts_in_spend_logs: false`), so a consumer's question does not outlive the request in the gateway's database.
- **Managed credentials:** The gateway master key and the admin UI password are generated and kept as role credentials, and the admin UI username is the platform administrator name.

## Central gateway for several hosts

One host can serve the gateway to every other host of a deployment over the
WireGuard mesh, so a small host such as a Raspberry Pi runs no gateway of its
own and models, provider keys and spend stay in one place.

1. Put every host on one mesh with `cli.administration.inventory.mesh`. A
   consuming host reaches the gateway at the mesh address its own interface
   lists for the gateway host, so the gateway host is the hub of that mesh or
   a member of a full mesh.
2. In the host_vars of each consuming host, name the gateway host by its
   inventory hostname, and leave `svc-ai-litellm` out of that host's
   inventory:

   ```yaml
   applications:
     svc-ai-litellm:
       services:
         litellm:
           gateway_host: echoserver
   ```

3. Run the pass over every inventory of the deployment, naming the
   `LITELLM_CHAT_MODEL` of the gateway host once:

   ```bash
   python -m cli.administration.inventory.gateway \
     --inventory inventories/echoserver/devices.yml \
     --inventory inventories/galaxyserver/devices.yml \
     --host-vars-dir inventories/host_vars \
     --vault-password-file inventories/.password \
     --host-vault-password-file galaxyserver=inventories/galaxyserver/.password \
     --chat-model echoserver=llama3.2:1b
   ```

   It writes `gateway_url` and `gateway_model` into each consuming host's
   `services.litellm`, one key per consuming host into that host's
   `credentials.gateway_key` and into the gateway host's
   `credentials.host_keys`, each encrypted with the vault password of the host
   that holds it. A re-run changes no file.
4. Deploy the gateway host first: it registers each consuming host's key
   under the alias `host:<hostname>` and publishes its port on its mesh
   address beside the loopback one. Then deploy each consuming host. Its
   deploy asks the gateway for its model list over the mesh before any
   consumer is configured and stops with the gateway host and URL named when
   the gateway does not answer, refuses the key or does not serve the chat
   model.

On a consuming host every consumer uses the mesh URL and the host's key, so
no consumer role carries a branch of its own. Inventory provisioning leaves
`svc-ai-litellm` out of such a host, and a host that carries it while naming
a gateway host fails its deploy. The mesh publish is a compose feature: in
swarm the engine does not honour a bind address, so a swarm gateway host does
not answer on its mesh address.

**Rotate the key of one host:** re-run the pass with `--rotate <hostname>`,
then deploy the gateway host and that consuming host. Every other host keeps
its key.

**Revoke a host:** clear its `gateway_host`, re-run the pass and deploy the
gateway host. The pass drops the host's URL, model and key, and the gateway
deletes every `host:` key no consuming host holds any more.

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

Matrix variant 0 deploys FreeLLMAPI with every check enabled. Its own variant
seeds a deterministic test upstream as the only provider, so the checks run
against the real FreeLLMAPI routing and translation without a provider account.
Variants 1 and 2 switch FreeLLMAPI off. FreeLLMAPI supports Compose only, so a
Swarm round disables it through the round's `disable` list.

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
cooldown are retried, and so is an HTTP 400 reporting `Engine protocol predict
request failed: fetch failed`: LM Studio answers a lost connection to its own
inference engine with that 400, which LiteLLM forwards as a request error. The
validator honors numeric and HTTP-date `Retry-After`
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
