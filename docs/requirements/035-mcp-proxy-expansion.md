# 035 - MCP Proxy Expansion and Application Interconnection

## User Story

As a platform administrator of Infinito.Nexus, I want every role with an `application_id` to have an explicit, evidence-based MCP disposition and every suitable application to expose a narrowly curated MCP surface to Open WebUI, Flowise, n8n, and other approved clients so that applications can be connected without turning shared administrator credentials, raw infrastructure APIs, or arbitrary network access into agent tools.

## Scope

This requirement extends [025 - MCP Role Integration](025-mcp-role-integration.md).
Requirement 025 defines the initial MCP metadata and the first Open WebUI integration; this requirement defines the exhaustive role audit, proxy and workflow-adapter contract, client reconciliation, and the conditions under which the remaining roles may be integrated.

The repository snapshot evaluated for this requirement contains 172 roles with a literal `application_id` and 18 role-local `mcp:` blocks.
The audit below classifies every one of those 172 roles exactly once.
The snapshot is planning evidence, not a second runtime registry: implemented surfaces remain authoritative in each role's `meta/services.yml`, while a generated lint test MUST prove that every current `application_id` still has a disposition.

This requirement covers requirement and design work only.
It does not authorize enabling a new MCP endpoint, upgrading an application, installing an upstream plugin, or widening a credential in the same change that introduces this document.

## Findings That Constrain the Design

The implementation MUST start from the current code rather than from the completed checkboxes in requirement 025:

- [`plugins/lookup/mcp_servers.py`](../../plugins/lookup/mcp_servers.py) currently reads every provider token from `users.administrator.tokens` and copies that deployment credential to every selected client. `auth_subject` is returned as metadata but does not select or verify the real credential owner.
- [`plugins/filter/mcp/authorization.py`](../../plugins/filter/mcp/authorization.py) renders `oidc` as a stored bearer value. It does not acquire, refresh, exchange, or revoke an end-user OAuth token. A rendered deployment bearer MUST therefore be classified as `service_account`, never as user delegation or on-behalf-of.
- [`plugins/lookup/roles_with_service.py`](../../plugins/lookup/roles_with_service.py) discovers all shared providers without a consumer allowlist. Several current role flags also name concrete peer roles in `group_names`, which cannot scale to Flowise, n8n, LiteLLM, and future clients.
- [`roles/web-app-openwebui/tasks/utils/mcp.yml`](../../roles/web-app-openwebui/tasks/utils/mcp.yml) and [`roles/web-app-openwebui/files/python/provision_mcp_grants.py`](../../roles/web-app-openwebui/files/python/provision_mcp_grants.py) can resolve or create an Open WebUI group by its path-like name and then write the generated group identifier into `access_grants`. This is the correct deployment-controlled mechanism, but application-specific Keycloak membership, last-group revocation, and restart reconciliation remain mandatory gaps.
- [`roles/web-app-openwebui/templates/env.j2`](../../roles/web-app-openwebui/templates/env.j2) sets `ENABLE_PERSISTENT_CONFIG=false`. API changes to environment-backed connection state MUST be treated as runtime state that has to be reconciled after every container restart; a deploy-only one-shot is insufficient.
- [`roles/web-app-flowise/vars/main.yml`](../../roles/web-app-flowise/vars/main.yml) currently computes discovery data but no task registers it. [`roles/web-app-flowise/templates/env.j2`](../../roles/web-app-flowise/templates/env.j2) disables `HTTP_SECURITY_CHECK` globally when MCP servers are present, and [`roles/web-app-flowise/files/playwright/test-mcp.js`](../../roles/web-app-flowise/files/playwright/test-mcp.js) proves only that an anonymous chatflow call is rejected.
- The exact Flowise 3.1.4 source provides authenticated create, list, update, authorize, delete, and tool-list routes under `/api/v1/custom-mcp-servers`. It stores custom-header authentication encrypted and binds entries to the active workspace. Its authorization path passes `sse` to the toolkit, but that argument only selects stdio versus HTTP: for any URL the toolkit attempts Streamable HTTP first and falls back to SSE through `secureFetch`, whose `node-fetch` response body the MCP SDK rejects with `expected a web ReadableStream`. The pinned release therefore registers Streamable HTTP providers and cannot register SSE ones.
- The exact n8n 1.95.3 source contains an SSE MCP Client Tool and an SSE MCP Server Trigger. Its public API can create credentials and workflows and activate workflows. The newer instance-wide administration MCP service MUST NOT be attributed to this pinned release.
- [`roles/svc-ai-litellm/meta/services.yml`](../../roles/svc-ai-litellm/meta/services.yml) pins `main-v1.77.3.dynamic_rates`. Its current role contract is an inference gateway. It MUST remain only an inference gateway until source inspection and an end-to-end test of a new explicit pin prove the required MCP gateway behavior.
- [`roles/svc-ai-mcp-adapter/tasks/probe.yml`](../../roles/svc-ai-mcp-adapter/tasks/probe.yml) proves the endpoint answers its declared contract, not that any particular client can route to it: it runs in a throwaway container joined to the *provider's* own network, because an `expose:`-only endpoint resolves nowhere else. Per-client routing is therefore still unproven by any test. Measured by hand on compose, Open WebUI resolves `baserow` to `192.168.206.4` and `homeassistant` to `192.168.79.2`, both distinct from the wildcard address, so the topology carries those two pairs; Swarm is unmeasured. [`isolation.yml`](../../roles/svc-ai-mcp-adapter/tasks/isolation.yml) does cover the adapter half, counting networks inside the sidecar for every `implementation: adapter` provider.
- Only Open WebUI carries a per-server user boundary, through the `mcp` RBAC group it grants per provider. Flowise and OpenClaw instead declare an `mcp` role their auth proxy admits alongside `administrator`, which is the documented trust domain the criterion allows: holding it reaches every provider that client is admitted to. n8n's MCP block is disabled. Hermes has neither: `meta/rbac.yml` declares `roles: {}` and `services.sso.enabled` is false, so its whole MCP surface is bounded by the shared `API_SERVER_KEY` alone. Whether that counts as an isolated trust domain is an operator decision, not something the declarations settle.
- The adapter `digest` pins nothing today. All ten `implementation: adapter` roles carry the identical placeholder `sha256:` followed by sixty-four zeros, the schema only checks that prefix, and nothing outside the tests reads the field: the running image is resolved through `lookup('container_image', …)` from `services.mcp-adapter.image`. The immutable-source guarantee is therefore declared and not in force, so a lint that rejects a placeholder digest MUST land together with real digests rather than before them.
- `allowed_consumers` creates no network edge. A client reaches a provider only when the provider declares a `kind: mcp_client` consumer in its `meta/networks.yml`, or when the client happens to declare that provider as a service for an unrelated reason. Four of twenty providers declare the opening (gitlab, homeassistant, moodle, nextcloud); the other sixteen admit consumers they cannot serve, four of them enabled (baserow, gitea, jenkins, mattermost). Measured: deploying Hermes fails at its own probe with `All connection attempts failed` against `http://prometheusmcp:8080/mcp`, because `hermes` joins `[gitlab, hermes, homeassistant, litellm, moodle]` while `prometheusmcp` joins `[prometheus]` alone, and the adapter sidecar's isolation check asserts exactly that single attachment. Open WebUI reaches Baserow only because it also declares `services.baserow`. Per-pair networks therefore have to replace `kind: mcp_client`, which opens a provider to every client rather than to the admitted one.
- Opening an adapter provider's network to its clients collides with the sidecar isolation invariant, so one of the two has to give. A provider that declares the `mcp_client` overlay puts its own containers on it: `homeassistant` joins `[homeassistant, homeassistant_default]`. The same declaration on an adapter provider would give its sidecar a second interface, and [`isolation.py`](../../roles/svc-ai-mcp-adapter/files/python/probe/isolation.py) rejects anything but exactly one, because a sidecar holding the provider's credential must reach that provider only. Today `prometheusmcp` satisfies it with a single attachment and is therefore reachable by no client at all. Either the sidecar joins only the pair network and the provider joins it too, or the isolation check becomes an identity check over the admitted peers rather than a count.
- Hermes renders its agent config and its env from the same discovery list within one pass, and they disagree. Measured on compose: `config/config.yaml` written at 17:07:54 carries `web_app_prometheus` with `Authorization: "Bearer ${env:WEB_APP_PROMETHEUS_MCP_TOKEN}"`, while `.env/env` written at 17:07:51 defines no `*_MCP_TOKEN` at all, although [`templates/env.j2`](../../roles/web-app-hermes/templates/env.j2) loops over the same `HERMES_MCP_SERVERS` unconditionally. The client therefore presents an empty bearer and the adapter answers `401`, which is correct behaviour on its side: probed from inside, `prometheusmcp` returns `200` for its own bearer and `401` for a wrong one. Any fix has to make the env and the config provably render from one evaluation of the list rather than two.
- A shared infrastructure network carries lateral reach between the applications that join it, so `allowed_consumers` is an application-layer decision the network does not enforce. Measured on the compose stack: Flowise and Baserow both join `postgres` because both use the central database, and Flowise opens `baserow:80` at `192.168.200.5` although Baserow does not admit Flowise as a consumer. A client whose users can name a URL is bounded only by its deny list, which covers loopback, link-local metadata and multicast but no application host. Reach MUST be measured by resolved address, never by name: an unknown name falls through to a wildcard resolver that answers with one reachable address, so a name-based probe reports every peer as reachable and proves nothing. Bounding lateral reach needs a network policy or per-pair networks rather than the current shared-service topology.

The implementing agent MUST start its upstream source audit from these project-owned repositories or exact tags and MUST record the selected immutable version in the implementing PR:

| Capability | Authoritative source entry point |
|---|---|
| Flowise registry at the deployed pin | [Flowise tag `flowise@3.1.4`](https://github.com/FlowiseAI/Flowise/tree/flowise%403.1.4), especially `packages/server/src/routes/custom-mcp-servers/` and `packages/server/src/services/custom-mcp-servers/` |
| n8n client, trigger, and public provisioning API | [n8n tag `n8n@1.95.3`](https://github.com/n8n-io/n8n/tree/n8n%401.95.3), especially `packages/@n8n/nodes-langchain/nodes/mcp/` and `packages/cli/src/public-api/v1/handlers/` |
| WordPress plugin path | [`WordPress/mcp-adapter`](https://github.com/WordPress/mcp-adapter) |
| Discourse sidecar path | [`discourse/discourse-mcp`](https://github.com/discourse/discourse-mcp) |
| Qdrant sidecar path | [`qdrant/mcp-server-qdrant`](https://github.com/qdrant/mcp-server-qdrant) |
| ERPNext/Frappe plugin path | [`frappe/mcp`](https://github.com/frappe/mcp) |
| Matomo plugin candidate | [`matomo-org/plugin-McpServer`](https://github.com/matomo-org/plugin-McpServer) |
| Penpot interactive server | [`penpot/penpot-mcp`](https://github.com/penpot/penpot-mcp) |
| MariaDB isolated sidecar path | [`MariaDB/mcp`](https://github.com/MariaDB/mcp) |
| Redis blocked sidecar path | [`redis/mcp-redis`](https://github.com/redis/mcp-redis) |
| LiteLLM gateway candidate | [`BerriAI/litellm`](https://github.com/BerriAI/litellm) |

An upstream README or current default branch MAY identify a candidate, but only the source and tests of the exact selected tag or digest may close a compatibility criterion.

The reconciliation stage MUST run before the end-to-end tests that read the converged state, and MUST NOT sit behind a task that a red test aborts. Placed in the destructor stage it ran after the Playwright suite, and `any_errors_fatal` meant any failing role skipped reconciliation entirely, so the suite asserted a state nothing had produced yet.

A relative `include_tasks` resolves against the including file's directory when that file was reached by path, and against `tasks/` when it was reached through `tasks_from`. A file under `tasks/utils/` therefore loads from its own role and fails from the reconciler, unchanged. Every include below a `tasks_from` entrypoint MUST name a path that holds under both bases.

Open WebUI stores its tool servers in its own configuration, so a deployment that already holds connections answers every later read with them. A client MUST reconcile that answer against the declared set instead of adopting it: reading it as the desired state leaves a newly declared provider registered nowhere and a rotated bearer registered stale, in both cases without a failure. Clients that render their whole configuration each run, such as Hermes and OpenClaw, do not carry this class.

A role that gains a `shared_net` overlay changes its network layout: the project's default network, named after the entity and carrying the declared local subnet, is replaced by an unnamed project default, and the entity name passes to an externally managed network. Docker cannot relabel an existing network, so on a deployment that already ran, the network has to be recreated, and that fails while any consumer holds an endpoint on it:

```text
Network baserow Removing
Error response from daemon: error while removing network: network baserow has active endpoints (name:"hermes")
```

The hazard is ordering-dependent, not universal: it fires only when a consumer already holds an endpoint at the moment the provider first renders with the overlay. A provider that renders first migrates cleanly and never sees it, which is why some roles pass and others abort on the same change. Purging the provider's stack does not help, because the project label lives on the Docker network rather than in the compose directory. A fresh deployment is unaffected, so this never appears in CI.

The token store is written on `STACK_HOST` while every `lookup('users').tokens` reader executes on the Ansible controller. In compose the two are one machine; in swarm they are not, so a provider that mints and persists its credential still resolves to an empty bearer for every client. The store therefore has to reach the controller as well.

A client MUST NOT treat an unreachable provider as fatal while the play is still running. Roles deploy in dependency order, so a client that probes during its own role can run before a provider exists at all, and aborting there prevents that provider from ever deploying. This is the same exemption `credential_missing` already carries, and it ends the same way: the reconciliation stage probes with `MCP_RECONCILE_STRICT` once every provider has run, and a provider still unreachable there is a real failure.

Swarm attaches every task to `docker_gwbridge` for ingress and egress. A sidecar isolation check that compares attached addresses against the provider's declared subnets MUST accept that interface, or it rejects every sidecar in swarm while proving nothing about application reachability.

An application that authenticates its own API with a bearer MUST expose that path through the SSO ACL whitelist. The proxy cannot validate an application bearer, so a fully gated vhost answers an API call with an identity-provider redirect, which a client following redirects reads as a successful 200.

## Architecture Decision

The platform MUST NOT deploy one all-powerful OpenAPI-to-MCP process holding administrator credentials for every application.
It MUST provide one reusable, immutable adapter implementation but instantiate it once per provider application or per equally isolated trust domain.
Each adapter instance MUST attach only to the provider's existing local network, receive only that provider's least-privileged credential, expose a distinct MCP endpoint, and remain addressable by the provider's `application_id`.

The precedence is:

1. A supported native MCP endpoint with an enforceable tool policy.
2. A pinned, source-audited upstream plugin.
3. A pinned, isolated upstream sidecar.
4. A repository-owned allowlist adapter or a repository-owned n8n workflow.
5. A documented blocker when none of the above can preserve the application's authorization boundary.

Flowise and Open WebUI are clients, not generic security gateways.
n8n MAY adapt a workflow to MCP when its project, credential, input schema, and exposed workflow tools are deployment-managed.
LiteLLM MAY become a routing or policy layer only after the exact selected image is pinned and proven; it MUST NOT become the sole holder of all application administrator credentials.

Every exposed provider remains a separate logical MCP server even when a common proxy implementation serves it.
This preserves the mapping between `roles/<provider-application-id>/mcp`, the client connection, the upstream credential, the tool allowlist, and the audit record.

## Target Metadata Contract

Every role with an `application_id` MUST contain one role-local `mcp:` audit mapping in `meta/services.yml`.
This requirement supersedes requirement 025's rule that absence means no upstream path, because absence cannot distinguish a reviewed refusal from a role that nobody examined.
Discovery MUST select only a deployable classification with explicit `enabled: true` and `shared: true`; audit-only mappings MUST never become endpoints.

An audit-only mapping MUST use this minimal explicit form:

```yaml
mcp:
  classification: no_surface
  reason: host_execution_boundary
  notes: This desktop role has no isolated remote application identity or endpoint.
```

Allowed classifications MUST be `native_server`, `native_client`, `native_both`, `plugin_server`, `sidecar_server`, `adapter_server`, `adapter_candidate`, `blocked`, `enabler`, `subordinate`, and `no_surface`.
Allowed reasons MUST be documented and linted, including `no_remote_surface`, `host_execution_boundary`, `privileged_control_plane`, `shared_engine_isolation`, `administrative_surface`, `duplicate_owner`, `version_unverified`, `licence`, `hosted_only`, `stdio_only`, `interactive_browser_session`, `unreviewed_third_party`, and `missing_dependency`.
A deployable mapping MUST additionally carry the source URL and exact supported version or source commit; a negative classification MUST carry a concrete reason and explanatory notes.

The shared service schema MUST also add explicit adapter and consumer fields.
There are no implicit security defaults: every field shown below is required for an enabled adapter surface, and a missing value MUST fail lint or deployment.

```yaml
mcp:
  classification: adapter_server
  enabled: true
  shared: true
  direction: server
  transport: sse
  exposure: internal
  auth: bearer_token
  auth_subject: service_account
  credential:
    owner: mcp-service-web-app-example
    source: token_store
    key: web-app-example
  implementation: adapter
  maturity: experimental
  source_url: https://example.invalid/project/source/tree/v4.5.6
  supported_version: 4.5.6
  allowed_consumers:
    - web-app-openwebui
    - web-app-flowise
  endpoint:
    service_key: example-mcp
    path: /mcp
    port_key: http
  adapter:
    type: openapi_allowlist
    image: registry.example.invalid/infinito-mcp-adapter
    version: 1.2.3
    digest: sha256:0123456789abcdef
    upstream_api_version: v1
    specification_path: files/mcp/openapi-v1.json
    specification_sha256: sha256:fedcba9876543210
  limits:
    request_bytes: 65536
    response_bytes: 1048576
    timeout_seconds: 15
    concurrent_requests: 4
    page_size: 100
    result_items: 500
    stream_seconds: 300
  tools:
    allowlist:
      - example_search
      - example_get
    schema_sha256: sha256:abcdef0123456789
    read_only_default: true
    mutating_tools_enabled: false
```

Allowed implementation values MUST become `native`, `plugin`, `sidecar`, `adapter`, and `external`.
An `adapter` MUST declare exactly one of these types:

- `openapi_allowlist`: a checked-in, versioned, hash-pinned API description plus explicit operation identifiers;
- `graphql_allowlist`: checked-in persisted operations only, with runtime introspection and arbitrary query text rejected;
- `named_query`: checked-in parameterized read queries or views through an application-specific read-only database principal, never arbitrary SQL;
- `s3_prefix`: list, head, and get through a dedicated read-only policy restricted to named buckets and prefixes;
- `prometheus_readonly`: query, query-range, labels, metadata, and targets with explicit lookback, sample, response, and timeout limits;
- `n8n_workflow`: a checked-in workflow with a stable ownership marker, explicit input schema, explicit connected tools, and bearer-protected SSE trigger;
- `resource_readonly`: checked-in rules for exposing a bounded, non-secret published content set as MCP resources rather than pretending it is an application action API.

The schema MUST reject a generic URL, runtime OpenAPI document, free-form GraphQL query, raw SQL tool, unrestricted bucket, arbitrary filesystem root, shell command, Docker socket, or implicit exposure of every operation added by an upstream upgrade.

`allowed_consumers` MUST contain explicit client `application_id` values.
Discovery MUST require the provider to allow the consumer and the consumer to support the provider's transport and authentication scheme.
Authorized but unrenderable entries MUST fail reconciliation with a machine-readable reason; they MUST NOT disappear silently.

## Identity, Authorization, and Credential Requirements

### Provider identity

Each service-account integration MUST provision a dedicated non-login identity with only the upstream permissions needed by the declared tool allowlist.
The lookup MUST resolve `mcp.credential.owner`, `source`, and `key`; it MUST NOT hard-code `administrator`.
Deployment MUST fail if the resolved principal is missing, empty, more privileged than `auth_subject` declares, or shared with an unrelated provider.

Where an upstream supports real per-user OAuth, the implementation MAY set `auth_subject: user` only after the exact client and server prove authorization-code or token-exchange behavior, token refresh, audience/resource binding, logout/revocation, and expiry.
Passing a static bearer issued to the deployment is not on-behalf-of and MUST remain `service_account`.
Client-side group gating controls access to that service account; it does not recreate the caller's application permissions.

Credentials MUST be unique per provider and, when a provider cannot distinguish consumers, per provider-consumer pair.
Rotation MUST use an explicit two-phase procedure: issue new, reconcile every consumer, prove new works, revoke old, and prove old fails.
Disabling a surface or removing a consumer MUST revoke the related credential rather than merely hiding the connection.

Secrets MUST be sent in authenticated headers or a supported secret reference.
A URL path component selected by `key_credential` MUST be hidden behind an internal header-authenticated proxy or be proven non-secret.
Bearer values and secret path segments MUST be redacted from application logs, reverse-proxy logs, task output, Playwright traces, and exception messages.

### Application-scoped user grants

Every client connection MUST map to exactly one provider group named `roles/<provider-application-id>/mcp`.
The deployment MAY create or locate the corresponding client-local group by name after startup and then use the identifier assigned by the client API; it MUST NOT predict a generated group UUID.

The declarative user schema MUST gain an application-scoped role form, for example:

```yaml
users:
  alice:
    application_roles:
      web-app-baserow:
        - mcp
      web-app-zammad:
        - mcp
```

The exact schema name may change during implementation, but an unscoped `roles: [mcp]` MUST NOT grant every application's `mcp` role.
Direct Keycloak group membership remains valid, but both paths MUST converge on the exact application group in the OIDC claim.

Open WebUI access tests MUST cover a user with one of several MCP groups, a user with no MCP group, a user in the wrong application's group, and removal of the user's last group.
The known empty-group synchronization behavior MUST be fixed upstream, patched in the pinned image, or compensated by an explicit reconciliation/session-invalidation mechanism before strict revocation is claimed.

Flowise 3.1.4 binds registry entries to a workspace, not to the platform's per-application Keycloak groups.
Until an exact pinned Flowise version proves per-server user ACLs, deployment-managed MCP connections MUST live in an admin-only workspace or a separate Flowise trust-domain instance.
They MUST NOT be offered to every ordinary flow author merely because the user can sign into Flowise.
The same rule applies to Hermes, OpenClaw, n8n, and any future client lacking a tested per-server user authorization boundary.

### Keycloak as authorization enabler

`web-app-keycloak` MUST NOT expose its administration API as a general MCP tool server.
It MAY provide OAuth authorization infrastructure for MCP servers by provisioning an explicit resource/audience, client policy, scope, and redirect contract per provider.
Experimental token exchange MUST remain disabled for MCP until the exact Keycloak, client, and server versions pass user-delegation and revocation tests.

## Discovery and Reconciliation

A post-application MCP reconciliation stage MUST run after all selected provider roles have provisioned and probed their endpoints.
The stage MUST create one immutable discovery snapshot and reconcile Open WebUI, Flowise, Hermes, OpenClaw, and n8n from that snapshot.
It MUST run after initial deployment, provider credential rotation, provider MCP enable/disable changes, and a standalone client container restart.

No provider or client `enabled` or `shared` expression may enumerate concrete peer role names.
Provider enablement MUST be explicit operator/variant state or derived through a common direction-aware lookup.
Every client MUST declare supported transports and authentication schemes.
The discovery result MUST include selected entries and rejected entries with a stable rejection code such as `consumer_not_allowed`, `transport_unsupported`, `auth_unsupported`, `credential_missing`, or `endpoint_unreachable`.

Reconciliation MUST use the ownership name `infinito:<provider-application-id>`.
It MUST update or remove only entries carrying that marker and preserve all human-created client configuration.
Zero matching entries creates one, one updates it, and more than one MUST fail without guessing which duplicate to keep.

Open WebUI has environment-backed configuration with persistence disabled.
The reconciler MUST reapply the complete desired connection and access grant after every process start, then verify it through the API.
Restarting only the Open WebUI container MUST converge to the same enabled connections and grants as a full deployment.

## Flowise 3.1.4 Integration

The current statement that Flowise lacks an instance-level registry is incorrect for the pinned version and MUST be removed from requirement 025 and the role README.
The deployment MUST use the authenticated `/api/v1/custom-mcp-servers` routes with a scoped API identity whose workspace permissions are limited to the required `tools:create`, `tools:view`, `tools:update`, and `tools:delete` operations.

For each compatible server the reconciler MUST:

1. List entries and select the exact deterministic name `infinito:<provider-application-id>`.
2. Create the entry when none exists or replace its complete desired state when exactly one exists.
3. Store authentication through Flowise's encrypted custom-header configuration rather than in flow JSON.
4. Call the entry's authorize route.
5. Verify `AUTHORIZED` status and the exact expected tool names and schema hash.
6. Delete a stale managed entry only when its name begins with `infinito:` and the provider is absent from the desired snapshot.

The role MUST build its own Flowise image from the pinned npm package. The published `flowiseai/flowise` tags `3.1.3`, `3.1.4` and `latest` all ship the `flowise` package at version 3.1.2, which serves none of the `custom-mcp-servers`, `mcp-server` or `mcp-endpoint` routes; upstream's Dockerfile runs an unpinned `npm install -g flowise` whose layer the release CI reuses across builds. The deployed version therefore MUST come from `npm install -g flowise@<version>`, and the served route set MUST be verified rather than inferred from the tag.

Flowise 3.1.4 MUST register only Streamable HTTP providers, because its SSE fallback cannot complete a connection at this pin.
An SSE provider MUST be reported as incompatible or placed behind a pinned, protocol-correct bridge; it MUST NOT be claimed as registered.
Supporting SSE directly requires an explicit Flowise upgrade whose exact source and end-to-end tests prove the transport.

The role MUST NOT solve internal connectivity by globally disabling SSRF protection for all flow authors.
If the exact pinned Flowise release cannot keep `HTTP_SECURITY_CHECK=true` for internal service DNS, the MCP workspace MUST be admin-only, egress MUST be restricted to a fixed-target MCP proxy, redirects MUST be disabled, DNS resolution MUST be revalidated at connection time, and network policy MUST prevent access to loopback, link-local metadata, unrelated application networks, and the container control plane.

A versioned managed chatflow or agentflow fixture MUST be created through a supported API, tagged with an Infinito ownership marker, and updated idempotently without overwriting human flows.
It MUST reference registry connections or encrypted Flowise credentials, never plaintext bearer values in `flowData`.
The end-to-end test MUST execute a deterministic MCP tool and assert its result; listing a connection or rejecting an anonymous chatflow request is insufficient.

## n8n 1.95.3 Integration

`web-app-n8n` MUST be added as `direction: both`, `transport: sse` for the exact pinned 1.95.3 behavior.
The deployment MUST use the public credential and workflow APIs through a least-scope API key persisted by the normal token store.

As a client, each managed MCP Client Tool node MUST use Bearer or Header authentication and an explicit include list.
The upstream `include: all` behavior MUST NOT be used for deployment-managed workflows.

As a server, each managed MCP Server Trigger workflow MUST:

- use a deterministic Infinito name and tag;
- require Bearer authentication rather than the upstream `none` option;
- connect only explicitly selected workflow tools with checked-in input schemas;
- be disabled until the operator enables that workflow adapter;
- publish its SSE endpoint only after activation and an authenticated MCP handshake;
- expose read-only operations first, with mutations in a separate opt-in variant and role.

The implementation MUST NOT claim that the newer instance-wide n8n administration MCP server exists in 1.95.3.
Using that surface requires a separately reviewed, explicit n8n upgrade.

## Upstream Paths Missing from Current Metadata

The following roles have a concrete upstream MCP or MCP-client path that is absent from, or incorrectly represented by, current metadata.
`candidate` means the path deserves implementation work; it does not mean that the current deployed version is safe or compatible.

| Role | Disposition | Required implementation or precise blocker |
|---|---|---|
| `svc-ai-litellm` | gateway candidate | Keep the current pin as inference-only. Select and pin an MCP-capable release only after source inspection proves per-server routes, exact tool allowlists, credential injection, and the chosen OAuth lifecycle. Use separate provider credentials and avoid a global administrator token. |
| `svc-ai-lmstudio` | client candidate | Replace the unversioned preview image with an explicit MCP-capable headless version, render only deployment-curated servers, disable arbitrary per-request URLs, and test tool allowlists. Otherwise classify `version_unverified`. |
| `svc-db-elasticsearch` | blocked direct path | The maintained native path requires Kibana Agent Builder, suitable index/application privileges, and licensing; the older sidecar is deprecated. Record `missing_kibana_and_licence` until those dependencies are explicit. |
| `svc-db-mariadb` | isolated-sidecar candidate | Never attach a global MCP server to the shared engine or root credential. Instantiate one sidecar per consuming application with a database-scoped read-only principal and only schema/SELECT/SHOW/DESCRIBE tools. Otherwise record `shared_engine_isolation`. |
| `svc-db-qdrant` | sidecar candidate | Pin the official Qdrant MCP server, require read-only mode, and provision one collection and key per application. No shared administrator key or all-collection visibility is allowed. |
| `svc-db-redis` | blocked direct path | The upstream server is stdio-oriented and broadly mutating. Keep `stdio_only_and_shared_cache` unless an isolated instance, prefix-scoped ACL principal, pinned bridge, and exact read-only tool list are supplied. Prefer using Redis as an internal agent-memory backend rather than a user-visible server. |
| `web-app-erpnext` | plugin candidate | Pin the experimental Frappe MCP component in a small managed app, expose a few named read tools, reject generic DocType/method/SQL execution, and use a restricted ERPNext API user or proven per-user OAuth. Verify against the exact Frappe v16 pin. |
| `web-app-matomo` | plugin candidate | Audit and pin the project-owned MCP plugin against the exact Matomo version. Expose reporting reads only and never share a superuser token. Leave blocked until endpoint, transport, auth, and tool scope are verified in source. |
| `web-app-n8n` | native client and server candidate | Implement the SSE client and bearer-protected SSE Trigger workflow contract in this requirement. Do not use features introduced only in n8n 2.13 or later. |
| `web-app-penpot` | interactive blocker | The project-owned server requires an active browser tab and plugin connection and can execute powerful design-context operations. Record `interactive_browser_session`; only an experimental user-initiated integration with a pinned server and isolated session may proceed. |
| `web-app-shopware` | version-gated native candidate | Current Shopware 6.7.8.2 predates the experimental native server. Upgrade only to an explicit tested release containing `/api/_mcp`, provision a dedicated minimal-ACL integration, and allowlist search/read tools. Keep write, delete, cache, state-machine, and configuration tools disabled. |

## Corrections to Existing MCP Metadata

The 18 roles already containing an `mcp:` block require the following revalidation before they count as complete:

| Role | Required correction or validation |
|---|---|
| `web-app-baserow` | Retain the native server only with a dedicated least-privilege identity, a verified read-only tool allowlist, per-consumer grants, and an actual client tool call. |
| `web-app-confluence` | Keep self-hosted deployment blocked while the verified Atlassian path is Cloud-only; an external connector must be explicit and must not be represented as the self-hosted role's endpoint. |
| `web-app-discourse` | Replace `hosted_only`. Pin the project-owned HTTP sidecar, force read-only mode, use a restricted User API key where possible, and protect the sidecar with client-facing auth. Writes require separate switches and explicit opt-in. |
| `web-app-flowise` | Reconcile the 3.1.4 Streamable HTTP registry and a managed flow as defined above. Remove the global-security-relaxation-as-integration claim and replace the anonymous-only test with a deterministic tool call. |
| `web-app-gitea` | Verify the exact project-owned package, image pin, endpoint auth, dedicated service account, tool allowlist, and read-only behavior. |
| `web-app-gitlab` | Keep tier and exact self-managed endpoint availability as hard gates. Use a project/group-scoped token and exclude mutation tools until separately enabled. |
| `web-app-hermes` | Keep `direction: client` unless a pinned authenticated stdio-to-HTTP bridge is added. Document the server-side path as `server_stdio_only`; do not imply a deployable HTTP server. |
| `web-app-homeassistant` | Verify the exact native endpoint, transport, scopes, entity exposure, and service-call mutations. A long-lived administrator token is not acceptable. |
| `web-app-jenkins` | Pin the plugin and Jenkins compatibility, expose job/status/log reads first, and keep build/config/script actions outside the default tool list. |
| `web-app-jira` | Keep self-hosted deployment blocked while the verified Atlassian path is Cloud-only; any external connector requires its own credentials, URL, and data-boundary documentation. |
| `web-app-mattermost` | Replace administrator credentials with a dedicated bot/service identity and separate read/search tools from post/channel-management tools. |
| `web-app-moodle` | Pin a Moodle-compatible plugin, use an exact web-service function allowlist and restricted service user, and prove that unlisted functions cannot be invoked. |
| `web-app-nextcloud` | Pin the required apps, scope the application password/service account, constrain files and tools, and prove that the endpoint cannot escape that user's shares. |
| `web-app-odoo` | Replace `hosted_only` with `unreviewed_third_party`. Select no module until source, license, update cadence, transport, authentication, and model/operation allowlists pass review. |
| `web-app-openclaw` | Keep `direction: client` unless a pinned authenticated bridge proves server behavior. Do not persist raw MCP bearers in JSON; require a supported environment/file secret reference or retain a precise blocker. |
| `web-app-openproject` | Preserve the Community Edition licensing blocker. A future Enterprise variant must explicitly supply the edition/license and use a restricted OAuth application. |
| `web-app-openwebui` | Retain per-server group grants but remove the hard-coded administrator token source, add application-scoped user roles, fix last-group revocation, and reconcile after restart. |
| `web-app-wordpress` | Replace `hosted_only`. Pin the official WordPress MCP adapter, expose its HTTP endpoint, register only reviewed Abilities with permission callbacks, and authenticate as a real restricted user through Application Password or proven OAuth. |

## Curated Adapter Candidates

No role in this section has been proven to possess a safe native MCP server at its currently pinned version.
Each is a candidate for an isolated adapter or a managed n8n workflow only after the exact pinned upstream API, authentication, pagination, and error semantics are inspected.
The adapter MUST start with three to five named read tools, not a generated copy of the entire API.

| Family | Roles | Initial permitted surface | Mandatory additional guard |
|---|---|---|---|
| Search and observability | `svc-db-typesense`, `web-app-checkmk`, `web-app-prometheus` | Collection search; host/service status; PromQL query, query range, labels, metadata, and targets | Per-application collection/index, explicit lookback and sample caps, no configuration or administration endpoint |
| Content and storage | `web-app-bookwyrm`, `web-app-funkwhale`, `web-app-jellyfin`, `web-app-joomla`, `web-app-mediawiki`, `web-app-minio`, `web-app-opencloud`, `web-app-peertube`, `web-app-seaweedfs`, `web-app-xwiki`, `web-svc-libretranslate` | Catalog/page/library search and get; S3 list/head/get; translate and detect | User or service identity restricted to the intended library/site/bucket/prefix; no edit/upload/delete by default |
| Business applications | `web-app-akaunting`, `web-app-decidim`, `web-app-espocrm`, `web-app-fider`, `web-app-kix`, `web-app-listmonk`, `web-app-magento`, `web-app-pretix`, `web-app-snipe-it`, `web-app-suitecrm`, `web-app-taiga`, `web-app-yourls`, `web-app-zammad` | Named list, search, and get tools for the application's primary records | Dedicated role with field/tenant restrictions; no generic CRUD, no arbitrary filter language, and no Adobe Commerce claim for Magento Open Source |
| Federated social and messaging | `web-app-bluesky`, `web-app-bridgy-fed`, `web-app-friendica`, `web-app-mailu`, `web-app-mastodon`, `web-app-matrix`, `web-app-mobilizon`, `web-app-pixelfed`, `web-app-postmarks`, `web-app-socialhome`, `web-svc-xmpp` | Search or read public/user-visible content and account state | Per-user token is required for private feeds, rooms, messages, or mail; a shared service account MUST NOT merge users' private data |
| High-side-effect operations | `web-app-bigbluebutton`, `web-app-jitsi`, `web-app-opentalk`, `web-app-pihole`, `web-app-semaphore` | Meeting/status/job/log reads only | Create/end meeting, DNS blocking changes, playbook/Terraform/shell execution, and configuration changes require a separate role, human confirmation, idempotency key, and audit event |

The first implementation investigation for each candidate MUST use the following starter contract.
Tool names are proposed repository contracts, not claims that upstream already uses those names.
If the exact pinned version cannot implement the named contract through a stable authenticated API, the role MUST be changed to `blocked` with the observed reason rather than receiving a generic substitute.

| Role | Proposed adapter | Initial tool contract | Identity and hard boundary |
|---|---|---|---|
| `svc-db-typesense` | `openapi_allowlist` | `typesense_search`, `typesense_get_document` | One search-only key and explicit collection list per application; no collection/schema/key administration |
| `web-app-akaunting` | `openapi_allowlist` | `akaunting_list_invoices`, `akaunting_get_invoice`, `akaunting_list_accounts` | Restricted company user/token; no payment, ledger, tax, user, or configuration mutation |
| `web-app-bigbluebutton` | `n8n_workflow` | `bbb_list_meetings`, `bbb_get_meeting`, `bbb_list_recordings` | Dedicated integration secret; no create, join-as-moderator, end, publish, or delete |
| `web-app-bluesky` | `n8n_workflow` | `bluesky_get_profile`, `bluesky_search_posts`, `bluesky_get_feed` | Per-user OAuth/app password for non-public data; no post, like, follow, moderation, or account mutation |
| `web-app-bookwyrm` | `openapi_allowlist` | `bookwyrm_search_books`, `bookwyrm_get_book`, `bookwyrm_get_public_shelf` | Public access or restricted user token; no shelf, review, follow, or federation mutation |
| `web-app-bridgy-fed` | `resource_readonly` | `bridgy_get_actor`, `bridgy_get_public_activity`, `bridgy_get_bridge_status` | Public data only; block if the pinned service has no stable bounded read API |
| `web-app-checkmk` | `openapi_allowlist` | `checkmk_list_hosts`, `checkmk_get_host_status`, `checkmk_list_services` | Automation user with monitoring-read permissions; no activation, acknowledge, downtime, host, rule, or password mutation |
| `web-app-decidim` | `graphql_allowlist` or `openapi_allowlist` | `decidim_search_processes`, `decidim_get_proposal`, `decidim_list_meetings` | Public reads first; no proposal, vote, moderation, identity, or assembly mutation |
| `web-app-espocrm` | `openapi_allowlist` | `espocrm_search_accounts`, `espocrm_get_contact`, `espocrm_list_cases` | Restricted CRM API user with field and team visibility; no generic entity endpoint or write |
| `web-app-fider` | `openapi_allowlist` | `fider_search_suggestions`, `fider_get_suggestion`, `fider_list_tags` | Public/restricted read token; no vote, response, status, tag, user, or tenant mutation |
| `web-app-friendica` | `n8n_workflow` | `friendica_get_profile`, `friendica_search_public_posts`, `friendica_get_timeline` | Per-user token for timeline data; no posting, messaging, contact, moderation, or account mutation |
| `web-app-funkwhale` | `openapi_allowlist` | `funkwhale_search_library`, `funkwhale_get_track`, `funkwhale_get_album` | Public or library-scoped identity; no upload, favorite, playlist, federation, or administration mutation |
| `web-app-jellyfin` | `openapi_allowlist` | `jellyfin_search_library`, `jellyfin_get_item`, `jellyfin_get_playback_status` | Dedicated non-admin user restricted by library policy; no stream URL, delete, playback control, user, or server mutation |
| `web-app-jitsi` | `n8n_workflow` | `jitsi_get_conference_status`, `jitsi_list_active_conferences` | Proceed only if the exact deployment exposes a stable authenticated status API; no room creation, moderation, recording, or token minting |
| `web-app-joomla` | `openapi_allowlist` | `joomla_search_content`, `joomla_get_article`, `joomla_list_categories` | Read-only API user; no article, extension, template, configuration, or user mutation |
| `web-app-kix` | `openapi_allowlist` | `kix_search_tickets`, `kix_get_ticket`, `kix_list_organizations` | Agent identity restricted to intended queues/organizations; no ticket, asset, user, or configuration mutation |
| `web-app-listmonk` | `openapi_allowlist` | `listmonk_list_campaigns`, `listmonk_get_campaign`, `listmonk_get_stats` | Reporting-only service identity; no subscriber export, message send, campaign start, template, or list mutation |
| `web-app-magento` | `graphql_allowlist` | `magento_search_products`, `magento_get_product`, `magento_get_category` | Storefront persisted queries only; do not treat Adobe Commerce preview MCP as available in Magento Open Source |
| `web-app-mailu` | `openapi_allowlist` | `mailu_get_domain_status`, `mailu_get_queue_summary`, `mailu_get_service_health` | Separate read-only administration principal if upstream supports one; no mailbox content, password, alias, domain, or queue mutation |
| `web-app-mastodon` | `openapi_allowlist` | `mastodon_get_profile`, `mastodon_search_public`, `mastodon_get_timeline` | Per-user OAuth for non-public timelines; no status, follow, favorite, direct-message, moderation, or account mutation |
| `web-app-matrix` | `n8n_workflow` | `matrix_list_rooms`, `matrix_search_messages`, `matrix_get_room_state` | Per-user access token and room membership; no cross-user service token, send, invite, kick, ban, power-level, or encryption-key action |
| `web-app-mediawiki` | `openapi_allowlist` | `mediawiki_search_pages`, `mediawiki_get_page`, `mediawiki_get_revision` | Anonymous/public or restricted bot read identity; no edit, upload, delete, block, rights, or configuration action |
| `web-app-minio` | `s3_prefix` | `minio_list_objects`, `minio_head_object`, `minio_get_object` | Dedicated read-only policy for declared buckets and prefixes; never root credentials, write, delete, policy, lifecycle, or admin APIs |
| `web-app-mobilizon` | `graphql_allowlist` | `mobilizon_search_events`, `mobilizon_get_event`, `mobilizon_list_groups` | Persisted public queries first; per-user token for private events; no create, join, invite, moderation, or federation mutation |
| `web-app-opencloud` | `n8n_workflow` | `opencloud_search_files`, `opencloud_get_metadata`, `opencloud_list_shared_files` | Restricted user/service identity and selected spaces; no unrestricted download URL, upload, share, permission, or user mutation |
| `web-app-opentalk` | `n8n_workflow` | `opentalk_list_rooms`, `opentalk_get_room`, `opentalk_get_recording_status` | Restricted API identity; no meeting start/end, invite, recording content, moderation, or tenant mutation |
| `web-app-peertube` | `openapi_allowlist` | `peertube_search_videos`, `peertube_get_video`, `peertube_get_channel` | Public reads or restricted account; no upload, comment, follow, federation, moderation, or administration mutation |
| `web-app-pihole` | `openapi_allowlist` | `pihole_get_status`, `pihole_get_query_summary`, `pihole_get_top_domains` | Reporting-only token if the exact API can enforce it; no query-log detail by default, blocking toggle, list, DNS, DHCP, or configuration mutation |
| `web-app-pixelfed` | `openapi_allowlist` | `pixelfed_get_profile`, `pixelfed_search_public`, `pixelfed_get_timeline` | Per-user OAuth for non-public data; no post, message, follow, moderation, or account mutation |
| `web-app-postmarks` | `resource_readonly` | `postmarks_search_public_bookmarks`, `postmarks_get_public_bookmark`, `postmarks_get_public_feed` | Public collection only; the single owner secret MUST NOT be exposed to a shared client |
| `web-app-pretix` | `openapi_allowlist` | `pretix_list_events`, `pretix_get_event`, `pretix_get_order_summary` | Organizer-scoped read token; redact attendee/payment data; no order, check-in, voucher, refund, payout, or event mutation |
| `web-app-prometheus` | `prometheus_readonly` | `prometheus_query`, `prometheus_query_range`, `prometheus_get_targets` | Fixed Prometheus origin, explicit lookback/sample/time caps; no admin, reload, snapshot, delete-series, or arbitrary URL proxy |
| `web-app-seaweedfs` | `s3_prefix` | `seaweedfs_list_objects`, `seaweedfs_head_object`, `seaweedfs_get_object` | Dedicated read-only S3 identity and declared bucket/prefix; no filer traversal outside the prefix, write, delete, replication, or admin action |
| `web-app-semaphore` | `openapi_allowlist` | `semaphore_list_projects`, `semaphore_get_task_status`, `semaphore_get_task_log` | Read-only project identity; no task start, playbook, Terraform, shell, repository, key, inventory, environment, or user mutation |
| `web-app-snipe-it` | `openapi_allowlist` | `snipeit_search_assets`, `snipeit_get_asset`, `snipeit_get_license_summary` | Read-only token with field restrictions; no checkout/checkin, asset, license, accessory, user, or settings mutation |
| `web-app-socialhome` | `resource_readonly` or `n8n_workflow` | `socialhome_get_profile`, `socialhome_search_public_content`, `socialhome_get_public_stream` | Public reads unless a proven per-user API exists; no content, follow, federation, moderation, or account mutation |
| `web-app-suitecrm` | `openapi_allowlist` | `suitecrm_search_accounts`, `suitecrm_get_contact`, `suitecrm_list_cases` | Restricted CRM API user and allowed modules/fields; no generic module CRUD, export, workflow, user, or configuration action |
| `web-app-taiga` | `openapi_allowlist` | `taiga_list_projects`, `taiga_get_issue`, `taiga_get_user_story` | Project-scoped read identity; no issue/story, sprint, membership, webhook, or project mutation |
| `web-app-xwiki` | `openapi_allowlist` | `xwiki_search_pages`, `xwiki_get_page`, `xwiki_get_attachment_metadata` | Read-only user restricted to named wikis/spaces; no page, attachment, script, rights, extension, or user mutation |
| `web-app-yourls` | `openapi_allowlist` | `yourls_expand_url`, `yourls_get_link_stats`, `yourls_search_links` | Read-only API identity if enforceable; never disclose the global signature token or enable shorten, edit, or delete by default |
| `web-app-zammad` | `openapi_allowlist` | `zammad_search_tickets`, `zammad_get_ticket`, `zammad_list_organizations` | Agent token restricted by Zammad groups; redact sensitive articles; no ticket, article, user, role, or configuration mutation |
| `web-svc-libretranslate` | `openapi_allowlist` | `libretranslate_detect`, `libretranslate_translate`, `libretranslate_list_languages` | Dedicated API key, strict text/request/response limits, and no arbitrary URL/file fetch |
| `web-svc-xmpp` | `n8n_workflow` | `xmpp_list_rooms`, `xmpp_get_room_state`, `xmpp_search_archive` | Per-user or room-scoped service identity; no unrestricted archive, send, invite, kick, ban, role, or server administration action |

`web-svc-collabora` and `web-svc-onlyoffice` MUST be reached through the owning document application's MCP boundary, such as Nextcloud or OpenCloud, rather than receiving a second independent service-account tool surface.

## Exhaustive Application-ID Audit

The following lists are the complete repository snapshot used to construct this requirement.
Implementation MUST replace the snapshot check with a test that derives the current set dynamically; it MUST NOT hard-code the number 172.

### Current MCP metadata requiring revalidation (18)

`web-app-baserow`, `web-app-confluence`, `web-app-discourse`, `web-app-flowise`, `web-app-gitea`, `web-app-gitlab`, `web-app-hermes`, `web-app-homeassistant`, `web-app-jenkins`, `web-app-jira`, `web-app-mattermost`, `web-app-moodle`, `web-app-nextcloud`, `web-app-odoo`, `web-app-openclaw`, `web-app-openproject`, `web-app-openwebui`, `web-app-wordpress`.

### Missing direct, plugin, sidecar, gateway, or client path (11)

`svc-ai-litellm`, `svc-ai-lmstudio`, `svc-db-elasticsearch`, `svc-db-mariadb`, `svc-db-qdrant`, `svc-db-redis`, `web-app-erpnext`, `web-app-matomo`, `web-app-n8n`, `web-app-penpot`, `web-app-shopware`.

### Curated adapter candidates (43)

`svc-db-typesense`, `web-app-akaunting`, `web-app-bigbluebutton`, `web-app-bluesky`, `web-app-bookwyrm`, `web-app-bridgy-fed`, `web-app-checkmk`, `web-app-decidim`, `web-app-espocrm`, `web-app-fider`, `web-app-friendica`, `web-app-funkwhale`, `web-app-jellyfin`, `web-app-jitsi`, `web-app-joomla`, `web-app-kix`, `web-app-listmonk`, `web-app-magento`, `web-app-mailu`, `web-app-mastodon`, `web-app-matrix`, `web-app-mediawiki`, `web-app-minio`, `web-app-mobilizon`, `web-app-opencloud`, `web-app-opentalk`, `web-app-peertube`, `web-app-pihole`, `web-app-pixelfed`, `web-app-postmarks`, `web-app-pretix`, `web-app-prometheus`, `web-app-seaweedfs`, `web-app-semaphore`, `web-app-snipe-it`, `web-app-socialhome`, `web-app-suitecrm`, `web-app-taiga`, `web-app-xwiki`, `web-app-yourls`, `web-app-zammad`, `web-svc-libretranslate`, `web-svc-xmpp`.

### Enabler or subordinate integration (4)

`svc-ai-mcp-adapter`, `web-app-keycloak`, `web-svc-collabora`, `web-svc-onlyoffice`.

`svc-ai-mcp-adapter` carries no MCP surface of its own. It is the adapter runtime a provider role instantiates, so its disposition is `enabler` and it MUST NOT appear in discovery as a provider or a consumer.

### No shared application MCP surface (96)

These roles remain out of shared MCP discovery.
A future exception requires a new requirement with a fixed operation list, dedicated identity, isolation boundary, human approval for mutations, and audit trail.

**`host_execution_boundary` (39):** `desk-bluray-player`, `desk-chromium`, `desk-copyq`, `desk-docker`, `desk-dotlinker`, `desk-firefox`, `desk-git`, `desk-gnome`, `desk-gnome-caffeine`, `desk-gnome-extensions`, `desk-gnome-terminal`, `desk-gnucash`, `desk-jrnl`, `desk-keepassxc`, `desk-libreoffice`, `desk-micro`, `desk-neovim`, `desk-nextcloud`, `desk-obs`, `desk-qbittorrent`, `desk-retroarch`, `desk-spotify`, `desk-ssh`, `desk-torbrowser`, `desk-virtualbox`, `desk-zoom`, `dev-arduino`, `dev-core`, `dev-java`, `dev-locales`, `dev-make`, `dev-nix`, `dev-nodejs`, `dev-python`, `drv-epson-multiprinter`, `drv-intel`, `drv-lid-switch`, `drv-non-free`, `gen-hunspell`.
These roles operate a workstation, developer toolchain, device, or host package; bridging them would amount to shared shell, filesystem, browser-session, device, or host execution without an application-specific remote identity.

**`privileged_control_plane` (23):** `svc-bkp-local-2-device`, `svc-bkp-nfs-2-local`, `svc-bkp-remote-2-local`, `svc-bkp-secrets-2-local`, `svc-bkp-volume-2-local`, `svc-dns-unbound`, `svc-net-tor`, `svc-net-wireguard-core`, `svc-net-wireguard-firewalled`, `svc-net-wireguard-plain`, `svc-opt-keyboard-color`, `svc-opt-ssd-hdd`, `svc-opt-swapfile`, `svc-prx-openresty`, `svc-registry-cache`, `svc-registry-docker`, `svc-runner`, `svc-storage-nfs-client`, `svc-storage-nfs-server`, `svc-swarm-manager`, `svc-swarm-node`, `svc-virt-kata`, `update`.
These roles can recover secrets, alter routing or host state, run code, change deployment state, or reach storage/control-plane sockets; they require a separate audited operations gateway and human approval rather than general-purpose application MCP.

**`shared_engine_isolation` (4):** `svc-db-memcached`, `svc-db-openldap`, `svc-db-postgres`, `svc-db-rabbitmq`.
A generic endpoint would bypass application and tenant authorization on a shared engine.
Any future exception requires a provider-application-specific account, namespace/database/schema/queue restriction, fixed named operations, and no engine administrator credential.

**`administrative_surface` (5):** `web-app-fusiondirectory`, `web-app-lam`, `web-app-pgadmin`, `web-app-phpldapadmin`, `web-app-phpmyadmin`.
These UIs expose identity or database administration rather than a bounded application-domain API and MUST NOT be represented by a shared service-account tool surface.

**`duplicate_owner` (1):** `web-app-litellm`.
This role is only the UI of the separately classified LiteLLM service role, which owns any future MCP gateway contract.

**`no_remote_surface` (24):** `svc-ai-ollama`, `svc-ai-robot`, `web-app-chess`, `web-app-dashboard`, `web-app-fediwall`, `web-app-hugo`, `web-app-littlejs`, `web-app-mig`, `web-app-mini-qr`, `web-app-navigator`, `web-app-roulette-wheel`, `web-app-sphinx`, `web-opt-rdr-domains`, `web-opt-rdr-www`, `web-svc-asset`, `web-svc-cdn`, `web-svc-coturn`, `web-svc-css`, `web-svc-file`, `web-svc-html`, `web-svc-legal`, `web-svc-logout`, `web-svc-mirror`, `web-svc-simpleicons`.
These roles have no independently useful authenticated remote action contract at the pinned implementation.
Static published content MAY later be consumed through one owning application's bounded `resource_readonly` adapter, but a new MCP sidecar that merely reimplements a static site's behavior does not count as integration.
Model tool calling in Ollama does not by itself make Ollama an MCP client or server.

## Tool and Adapter Safety Contract

Every adapter MUST enforce request size, response size, timeout, concurrency, pagination, result-row, and stream-duration limits with explicit values in role metadata.
It MUST log provider `application_id`, consumer `application_id`, tool name, credential subject, result status, duration, and correlation identifier without logging credentials or payload bodies.

Tool discovery MUST be allowlisted by exact name and JSON schema hash.
An unexpected added, removed, or changed upstream tool MUST fail closed until the checked-in contract is reviewed.
The policy gateway MUST enforce the same allowlist on `tools/call`; filtering only `tools/list` is insufficient.

Resources, prompts, sampling, elicitation, roots, and any protocol capability added by an upstream MCP release MUST be independently classified.
The absence of a dangerous tool list does not authorize an unreviewed non-tool MCP capability.

Mutations MUST be classified as reversible, irreversible, external-communication, financial, identity/permission, code-execution, or infrastructure-control.
Any enabled mutation requires a separate opt-in variant, a distinct RBAC role where practical, an idempotency strategy, a human confirmation boundary, and a tested audit event.
Infrastructure control, arbitrary code execution, unrestricted filesystem access, identity administration, and raw database mutation remain forbidden for shared clients.

Sidecars and adapters MUST use an immutable version and digest, documented provenance and license, a non-root user, read-only root filesystem, dropped Linux capabilities, no host or control-plane socket, explicit CPU/memory/PID limits, a provider-only network, and no unrelated outbound network access.

## Acceptance Criteria

### Audit and metadata

- [ ] A test discovers every role with a literal `application_id` and proves that it appears exactly once as `native_server`, `native_client`, `native_both`, `plugin_server`, `sidecar_server`, `adapter_server`, `adapter_candidate`, `blocked`, `enabler`, `subordinate`, or `no_surface`; absence is not an audit result.
- [ ] The operational metadata remains role-local, while the generated audit report includes deployed version, authoritative source, transport, authentication, real credential subject, read/write scope, tool allowlist, proposed implementation, selected consumers, and blocker.
- [ ] Lint accepts `implementation: adapter` only with one allowed adapter type and all mandatory immutable-source, credential, endpoint, limit, and tool-contract fields.
- [x] Lint rejects every generic URL/spec/query/SQL/filesystem/shell/socket/unrestricted-bucket surface described in this requirement.
- [ ] WordPress, Discourse, Odoo, Hermes, OpenClaw, Flowise, and the 11 missing upstream-path roles are reclassified exactly as required above before their old status is considered complete.

### Credentials and authorization

- [x] `mcp_servers` resolves the declared credential owner and source rather than `users.administrator.tokens`, and deployment fails for missing, empty, shared, or overprivileged credentials.
- [x] `auth_subject` is validated against the identity actually provisioned in the provider and is not documentation-only.
- [x] `auth: oidc` is rejected by static client renderers until a real acquisition, refresh, audience, expiry, and revocation flow is implemented and tested.
- [x] Open WebUI grants each server to only `roles/<provider-application-id>/mcp`; one-of-many, no-membership, wrong-app, removal, and last-group removal tests pass.
- [x] The declarative user configuration can assign `mcp` to one application without assigning it to any other application.
- [ ] Flowise, Hermes, OpenClaw, and n8n prove their per-server user boundary or are restricted to an admin-only workspace/instance or isolated trust domain.
- [ ] Rotation and disablement tests prove that the old credential is rejected, the new credential works, and no stale client entry retains access.
- [ ] Credentials and secret URL components are absent from logs, generated non-secret configuration, API responses, task output, Playwright traces, and exception text.

### Discovery and lifecycle

- [x] Providers declare explicit allowed consumers, clients declare supported transports/auth schemes, and discovery computes the intersection without naming peer roles in `group_names` expressions.
- [x] Every rejected discovery entry has a stable, tested reason; missing credentials, transport mismatch, and unreachable endpoints fail reconciliation when the consumer was explicitly authorized.
- [ ] One post-application reconciliation stage converges every selected client after provider provisioning, rotation, enable/disable changes, and standalone client restart.
- [x] Reconciliation owns only deterministically named resources, fails on duplicates, and preserves human-created resources. The ownership marker is per client, because the name is not always free: Flowise registry entries are `infinito:<provider-application-id>`, Open WebUI groups carry the RBAC group path Keycloak also issues, and n8n uses its configured workflow name.
- [ ] Compose and Swarm tests prove endpoint DNS/routing from each client and prove an adapter cannot reach unrelated application networks.
- [x] Open WebUI with `ENABLE_PERSISTENT_CONFIG=false` restores the exact desired connection state and group grants after a process restart without a full reinstall.

### Flowise and n8n

- [ ] Flowise 3.1.4 is reconciled through `/api/v1/custom-mcp-servers`, registers only Streamable HTTP providers, stores headers encrypted, authorizes each entry, and verifies exact tool names and schemas.
- [ ] Flowise Streamable HTTP support remains blocked or bridged until a pinned source-audited release passes an end-to-end tool call.
- [ ] Ordinary Flowise users cannot use MCP or another HTTP node to reach loopback, metadata endpoints, the container control plane, or unrelated internal services; globally disabling the SSRF check alone fails this criterion.
- [ ] A deployment-managed Flowise fixture executes a deterministic MCP tool successfully and contains no plaintext MCP credential.
- [ ] n8n 1.95.3 is declared as an SSE client and server, and its managed credentials and workflows are idempotently provisioned through supported public APIs.
- [ ] n8n client nodes use exact tool include lists; server triggers require Bearer auth, expose only connected checked-in tools, and remain disabled until operator opt-in.
- [ ] n8n tests cover creation, update, activation, authenticated tool listing and call, wrong/missing bearer rejection, rerun idempotence, and cleanup limited to managed resources.

### Provider and adapter behavior

- [ ] Each enabled native/plugin/sidecar provider passes an authenticated MCP handshake, exact tool-contract assertion, one deterministic read call, wrong-credential rejection, disabled-state rejection, and consumer-isolation test.
- [ ] Each enabled adapter proves the exact upstream identity and permission boundary, fixed target, operation allowlist, request/response limits, timeout, pagination, schema drift behavior, and redacted audit event.
- [ ] Database-backed integrations use per-application views/collections/indexes and read-only principals; no test or configuration contains a shared engine administrator credential.
- [ ] S3 adapters are restricted to declared bucket prefixes and list/head/get; Prometheus adapters enforce lookback/sample limits; GraphQL and SQL adapters reject arbitrary input languages.
- [ ] Mutating variants test human confirmation, authorization, idempotency, audit, and rollback or explicit irreversibility warning separately from read-only variants.
- [ ] Every client executes at least one deterministic real tool call. A server-list assertion, configuration render, connection authorize action, or anonymous API rejection alone does not satisfy end-to-end coverage.

## Implementation Order

1. Correct requirement 025's stale claims and add the exhaustive audit/lint status mechanism.
2. Remove the hard-coded administrator credential path, add provider-consumer authorization, add client capability filtering, and implement post-application reconciliation.
3. Make Open WebUI revocation and restart behavior correct before expanding its provider set.
4. Implement Flowise 3.1.4's Streamable HTTP registry and one deterministic read-only flow without disabling unrestricted SSRF protection.
5. Implement n8n 1.95.3 as an SSE client and one bearer-protected read-only workflow server.
6. Correct WordPress, then validate the existing native/plugin/sidecar roles one at a time.
7. Build the reusable adapter before any sidecar that depends on it. Source inspection of `discourse/discourse-mcp` and `qdrant/mcp-server-qdrant` shows both authenticate *to* their application and neither authenticates the MCP client calling them, so deploying either on its own would put an unauthenticated tool surface on the container network. Correcting Discourse and adding Qdrant therefore follows the adapter, not the other way round.
8. Add Qdrant with collection isolation and the high-value read adapters for Checkmk, Prometheus, LibreTranslate, Jellyfin, Pretix, Snipe-IT, Zammad, Listmonk, and Fider.
9. Evaluate Shopware upgrade, ERPNext plugin, Matomo plugin, LiteLLM gateway, and LM Studio client in focused requirements or PRs because each changes an upstream version or maturity boundary.
10. Add the remaining business, content, social, and operations adapters only after the shared contract and first high-value adapters pass Compose and Swarm tests.

## Prerequisites

Before implementation, the agent MUST read [AGENTS.md](../../AGENTS.md), the target role's `AGENTS.md` when present, [CONTRIBUTING.md](../../CONTRIBUTING.md), and the repository's agent and contributor guidance.
Any upstream capability MUST be verified against the exact image tag, source tag, or commit selected by the implementation; current documentation or a newer upstream release is not evidence for the deployed pin.
