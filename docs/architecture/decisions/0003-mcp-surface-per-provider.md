# 0003: One MCP surface per provider, and a disposition for every role 🔌

**Status:** accepted

Supersedes the design half of [025 - MCP Role Integration](../../requirements/025-mcp-role-integration.md), which assumed an empty baseline, treated metadata as enforcement, and marked client provisioning and end-to-end authorization complete.

> **Work:** the acceptance criteria and the order of implementation live in [035 - MCP Proxy Expansion and Application Interconnection](../../requirements/035-mcp-proxy-expansion.md).
> This record holds the decision, the forces behind it, the standing contract and the per-role audit; that document holds what is still to be built and which artifact proves each criterion.
> A disposition change belongs here, because the audit below is what two lints read. A newly met criterion belongs there.

## Context 🎯

An MCP client turns an application's API into tools a model may call. The cheap way to build that is one process holding administrator credentials for every application and translating an OpenAPI document into tools on demand. That process is a single credential store, a single network position reaching every application, and a tool surface that grows with every upstream release nobody reviewed.

Requirement 025 established the first metadata and the Open WebUI integration. Reading the code against it showed the gap between what was declared and what ran:

- [`plugins/lookup/mcp_servers.py`](../../../plugins/lookup/mcp_servers.py) read every provider token from `users.administrator.tokens` and copied that deployment credential to every selected client. `auth_subject` was returned as metadata and selected nothing.
- [`plugins/filter/mcp/authorization.py`](../../../plugins/filter/mcp/authorization.py) rendered `oidc` as a stored bearer. It acquired, refreshed, exchanged and revoked nothing, so a rendered deployment bearer was user delegation in name only.
- [`plugins/lookup/roles_with_service.py`](../../../plugins/lookup/roles_with_service.py) discovered all shared providers with no consumer allowlist, and several role flags named concrete peer roles in `group_names`, which does not scale past the first few clients.
- Absence of an `mcp:` block was the documented way to say "no upstream path", which cannot distinguish a reviewed refusal from a role nobody examined.

Three measurements decided the shape rather than any preference:

- **`allowed_consumers` creates no network edge.** A client reaches a provider only when the provider declares a `kind: mcp_client` consumer in `meta/networks.yml`, or when the client happens to declare that provider for an unrelated reason. Four of twenty providers declared the opening; the other sixteen admitted consumers they could not serve, four of them enabled. Deploying Hermes failed at its own probe with `All connection attempts failed` against `http://prometheusmcp:8080/mcp`, because `hermes` joins `[gitlab, hermes, homeassistant, litellm, moodle]` while `prometheusmcp` joins `[prometheus]` alone.
- **A shared infrastructure network carries lateral reach the application layer does not control.** On the compose stack, Flowise and Baserow both join `postgres` because both use the central database, and Flowise opens `baserow:80` at `192.168.200.5` although Baserow does not admit Flowise. Reach has to be measured by resolved address: an unknown name falls through to a wildcard resolver that answers with one reachable address, so a name-based probe reports every peer as reachable and proves nothing.
- **Opening an adapter provider's network to its clients collides with the sidecar isolation invariant.** A provider that declares the `mcp_client` overlay puts its own containers on it. The same declaration on an adapter provider would give its sidecar a second interface, and [`isolation.sh`](../../../roles/test-e2e-cli/files/shared/mcp/isolation.sh) rejects anything but exactly one, because a sidecar holding the provider's credential must reach that provider only.

Two further properties of the environment shaped the reconciliation design. Open WebUI stores tool servers in its own configuration and answers every later read with them, so a client that adopts that answer as the desired state leaves a newly declared provider registered nowhere and a rotated bearer registered stale, in both cases without a failure. And [`roles/web-app-openwebui/templates/env.j2`](../../../roles/web-app-openwebui/templates/env.j2) sets `ENABLE_PERSISTENT_CONFIG=false`, so API changes to environment-backed connection state are runtime state that has to be reconciled after every container restart.

## Decision ✅

**The platform does not deploy one all-powerful OpenAPI-to-MCP process.** It provides one reusable, immutable adapter implementation and instantiates it once per provider application or per equally isolated trust domain. Each instance attaches only to the provider's own network, receives only that provider's least-privileged credential, exposes a distinct endpoint, and stays addressable by the provider's `application_id`. Every exposed provider remains a separate logical MCP server even when a common implementation serves it, which preserves the mapping between `roles/<provider-application-id>/mcp`, the client connection, the upstream credential, the tool allowlist and the audit record.

**Integration paths are tried in this order**, and a lower one is used only when every higher one fails to preserve the application's authorization boundary:

1. a supported native MCP endpoint with an enforceable tool policy;
2. a pinned, source-audited upstream plugin;
3. a pinned, isolated upstream sidecar;
4. a repository-owned allowlist adapter or a repository-owned n8n workflow;
5. a documented blocker.

Flowise and Open WebUI are clients, not generic security gateways. n8n may adapt a workflow to MCP when its project, credential, input schema and exposed workflow tools are deployment-managed. LiteLLM may become a routing layer only after the exact selected image is pinned and proven, and must not become the sole holder of every application's administrator credential.

### Every role carries a disposition

Every role with an `application_id` carries one role-local `mcp:` mapping in `meta/services.yml`. Discovery selects only a deployable classification with explicit `enabled: true` and `shared: true`; an audit-only mapping never becomes an endpoint:

```yaml
mcp:
  classification: no_surface
  reason: host_execution_boundary
  notes: This desktop role has no isolated remote application identity or endpoint.
```

Allowed classifications are `native_server`, `native_client`, `native_both`, `plugin_server`, `sidecar_server`, `adapter_server`, `adapter_candidate`, `blocked`, `enabler`, `subordinate`, and `no_surface`.
Allowed reasons MUST be documented and linted, including `no_remote_surface`, `host_execution_boundary`, `privileged_control_plane`, `shared_engine_isolation`, `administrative_surface`, `duplicate_owner`, `version_unverified`, `licence`, `hosted_only`, `stdio_only`, `interactive_browser_session`, `unreviewed_third_party`, and `missing_dependency`.
A deployable mapping additionally carries the source URL and the exact supported version or commit; a negative classification carries a concrete reason and notes.

### An enabled adapter declares everything it is allowed to do

There are no implicit security defaults: every field below is required for an enabled adapter surface, and a missing value fails lint or deployment.

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

Allowed implementation values are `native`, `plugin`, `sidecar`, `adapter`, and `external`. An `adapter` declares exactly one type:

- `openapi_allowlist`: a checked-in, versioned, hash-pinned API description plus explicit operation identifiers;
- `graphql_allowlist`: checked-in persisted operations only, with runtime introspection and arbitrary query text rejected;
- `named_query`: checked-in parameterized read queries or views through an application-specific read-only database principal, never arbitrary SQL;
- `s3_prefix`: list, head and get through a dedicated read-only policy restricted to named buckets and prefixes;
- `prometheus_readonly`: query, query-range, labels, metadata and targets with explicit lookback, sample, response and timeout limits;
- `n8n_workflow`: a checked-in workflow with a stable ownership marker, explicit input schema, explicit connected tools, and a bearer-protected trigger;
- `resource_readonly`: checked-in rules for exposing a bounded, non-secret published content set as MCP resources rather than pretending it is an action API.

The schema rejects a generic URL, a runtime OpenAPI document, free-form GraphQL, a raw SQL tool, an unrestricted bucket, an arbitrary filesystem root, a shell command, a Docker socket, and implicit exposure of every operation an upstream upgrade adds.

### Identity is per provider, never the deployment administrator

Each service-account integration provisions a dedicated non-login identity holding only the upstream permissions the declared allowlist needs. The lookup resolves `mcp.credential.owner`, `source` and `key`; deployment fails when the resolved principal is missing, empty, more privileged than `auth_subject` declares, or shared with an unrelated provider.

`auth_subject: user` may be set only after the exact client and server prove authorization-code or token-exchange behaviour, token refresh, audience binding, revocation and expiry. A static bearer issued to the deployment is not on-behalf-of and stays `service_account`. Client-side group gating controls access to that service account; it does not recreate the caller's permissions.

Credentials are unique per provider and, where a provider cannot distinguish consumers, per provider-consumer pair. Rotation is two-phase: issue new, reconcile every consumer, prove new works, revoke old, prove old fails. Disabling a surface or removing a consumer revokes the credential rather than hiding the connection.

Every client connection maps to exactly one provider group named `roles/<provider-application-id>/mcp`. The declarative user schema carries an application-scoped role form, so `mcp` can be granted for one application without granting it everywhere:

```yaml
users:
  alice:
    application_roles:
      web-app-baserow:
        - mcp
      web-app-zammad:
        - mcp
```

`web-app-keycloak` does not expose its administration API as a tool server. It provides OAuth infrastructure for MCP servers by provisioning an explicit resource, client policy, scope and redirect contract per provider, with experimental token exchange disabled until the exact versions pass user-delegation and revocation tests.

### Discovery reconciles, and owns only what it named

One post-application reconciliation stage runs after every selected provider role has provisioned and probed its endpoint, builds one immutable discovery snapshot, and reconciles every client from it. No provider or client `enabled` or `shared` expression enumerates concrete peer role names. The discovery result carries selected entries and rejected ones with a stable code such as `consumer_not_allowed`, `transport_unsupported`, `auth_unsupported`, `credential_missing` or `endpoint_unreachable`.

Reconciliation updates or removes only entries carrying its own ownership marker and preserves human-created configuration. Zero matches creates, one updates, more than one fails rather than guessing which duplicate to keep. The marker is per client, because the name is not always free: Flowise registry entries are `infinito:<provider-application-id>`, Open WebUI groups carry the RBAC group path Keycloak also issues, and n8n uses its configured workflow name.

The stage runs before the end-to-end tests that read the converged state, and not behind a task a red test aborts. Placed in the destructor stage it ran after the Playwright suite, and `any_errors_fatal` meant any failing role skipped reconciliation entirely, so the suite asserted a state nothing had produced.

### The two clients with version-specific behaviour

**Flowise 3.1.4** is reconciled through the authenticated `/api/v1/custom-mcp-servers` routes with a scoped identity limited to `tools:create`, `tools:view`, `tools:update` and `tools:delete`. It registers only Streamable HTTP providers: its SSE fallback cannot complete a connection at this pin, so an SSE provider is reported incompatible rather than claimed as registered. The role builds its own image from the pinned npm package, because the published `flowiseai/flowise` tags `3.1.3`, `3.1.4` and `latest` all ship the `flowise` package at version 3.1.2, which serves none of the required routes. Internal connectivity is never solved by globally disabling SSRF protection for all flow authors.

**n8n 1.100.1** is `direction: both`: an SSE client and a Streamable HTTP server at MCP Server Trigger typeVersion 2. Managed client nodes use Bearer or Header authentication and an explicit include list, never upstream's `include: all`. Managed server triggers require Bearer authentication, connect only explicitly selected workflow tools with checked-in input schemas, stay disabled until the operator enables them, and expose read-only operations first.

### Safety contract for every adapter

Every adapter enforces request size, response size, timeout, concurrency, pagination, result-row and stream-duration limits with explicit values in role metadata, and logs provider, consumer, tool name, credential subject, result status, duration and correlation identifier without logging credentials or payload bodies.

Tool discovery is allowlisted by exact name and JSON schema hash, and an added, removed or changed upstream tool fails closed until the checked-in contract is reviewed. The policy gateway enforces the same allowlist on `tools/call`; filtering only `tools/list` is insufficient. Resources, prompts, sampling, elicitation, roots and any capability a future MCP release adds are classified independently, because the absence of a dangerous tool list does not authorize an unreviewed non-tool capability.

Mutations are classified as reversible, irreversible, external-communication, financial, identity/permission, code-execution or infrastructure-control. Any enabled mutation requires a separate opt-in variant, a distinct RBAC role where practical, an idempotency strategy, a human confirmation boundary and a tested audit event. Infrastructure control, arbitrary code execution, unrestricted filesystem access, identity administration and raw database mutation stay forbidden for shared clients.

Sidecars and adapters use an immutable version and digest, documented provenance and licence, a non-root user, a read-only root filesystem, dropped capabilities, no host or control-plane socket, explicit CPU/memory/PID limits, a provider-only network, and no unrelated outbound access.

### Per-provider constraints

The eighteen roles that already carried an `mcp:` block when this record was written each hold a standing constraint, because their surface was declared before the contract above existed:

| Role | Standing constraint |
|---|---|
| `web-app-baserow` | Native server only with a dedicated least-privilege identity, a verified read-only allowlist, per-consumer grants, and an actual client tool call. |
| `web-app-confluence` | Self-hosted stays blocked while the verified Atlassian path is Cloud-only; an external connector is explicit and is never represented as the self-hosted role's endpoint. |
| `web-app-discourse` | `stdio_only`, not `hosted_only`. The audit of `discourse/discourse-mcp` at `v0.3.1` closed the sidecar path: ownership, licence, pinning and read-only default pass, but the HTTP transport serves one session per process. Nothing is enabled until upstream supports concurrent sessions. |
| `web-app-flowise` | Reconciles the 3.1.4 Streamable HTTP registry and a managed flow. No global-security-relaxation-as-integration claim, and a deterministic tool call rather than an anonymous-rejection test. |
| `web-app-gitea` | Exact project-owned package, image pin, endpoint auth, dedicated service account, tool allowlist, read-only behaviour. |
| `web-app-gitlab` | Tier and exact self-managed endpoint availability are hard gates. Project/group-scoped token, mutation tools excluded until separately enabled. |
| `web-app-hermes` | `direction: client` unless a pinned authenticated stdio-to-HTTP bridge is added; the server-side path is `server_stdio_only`. |
| `web-app-homeassistant` | Exact native endpoint, transport, scopes, entity exposure and service-call mutations verified. A long-lived administrator token is not acceptable. |
| `web-app-jenkins` | Plugin and Jenkins compatibility pinned; job/status/log reads first; build, config and script actions outside the default tool list. |
| `web-app-jira` | Self-hosted stays blocked while the verified Atlassian path is Cloud-only; an external connector carries its own credentials, URL and data-boundary documentation. |
| `web-app-mattermost` | A dedicated bot/service identity instead of administrator credentials, and read/search tools separated from post/channel management. |
| `web-app-moodle` | A Moodle-compatible plugin pinned, an exact web-service function allowlist, a restricted service user, and proof that unlisted functions cannot be invoked. |
| `web-app-nextcloud` | Required apps pinned, application password scoped, files and tools constrained, and proof that the endpoint cannot escape that user's shares. |
| `web-app-odoo` | `unreviewed_third_party`, not `hosted_only`. The review ran and selected no module; re-review if Odoo SA or the OCA publishes a server. |
| `web-app-openclaw` | `direction: client` unless a pinned authenticated bridge proves server behaviour. Raw MCP bearers are never persisted in JSON. |
| `web-app-openproject` | The Community Edition licensing blocker stands. An Enterprise variant supplies edition and licence explicitly and uses a restricted OAuth application. |
| `web-app-openwebui` | Per-server group grants, no hard-coded administrator token source, application-scoped user roles, last-group revocation, reconciliation after restart. |
| `web-app-wordpress` | The official WordPress MCP adapter pinned, its HTTP endpoint exposed, only reviewed Abilities with permission callbacks registered, authenticated as a real restricted user. |

Five roles carry a concrete upstream path that the audit files as `blocked`; the blocker table above names what stops each one, and these are the conditions under which it would move:

| Role | Condition for reclassification |
|---|---|
| `svc-ai-litellm` | Keep the current pin inference-only. An MCP-capable release is selected only after source inspection proves per-server routes, exact tool allowlists, credential injection and the chosen OAuth lifecycle, with separate provider credentials rather than a global administrator token. |
| `svc-ai-lmstudio` | Replace the unversioned preview image with an explicit MCP-capable headless version, render only deployment-curated servers, disable arbitrary per-request URLs, and test tool allowlists. |
| `svc-db-mariadb` | One sidecar per consuming application with a database-scoped read-only principal and only schema/SELECT/SHOW/DESCRIBE tools. Never a global server on the shared engine or the root credential. |
| `web-app-erpnext` | Pin the experimental Frappe component in a small managed app, expose a few named read tools, reject generic DocType/method/SQL execution, and use a restricted API user or proven per-user OAuth, verified against the exact Frappe v16 pin. |
| `web-app-shopware` | Upgrade only to an explicit tested release containing `/api/_mcp`, provision a dedicated minimal-ACL integration, and allowlist search and read tools while write, delete, cache, state-machine and configuration tools stay disabled. |

## Exhaustive Application-ID Audit

Every role with a literal `application_id` is filed exactly once below. A role missing from these lists would read as "not yet looked at" and as "decided against" at the same time, with nothing to tell the two apart.

The section titles are the classification vocabulary itself, and each role that ships a `meta/mcp.yml` is filed under the value that file declares. [test_mcp_audit_completeness.py](../../../tests/lint/repository/documentation/test_mcp_audit_completeness.py) derives the role set from the repository rather than from this document, so a new role fails the lint until it is disposed of here, and [test_mcp_audit_classification.py](../../../tests/lint/repository/documentation/test_mcp_audit_classification.py) holds list and metadata apart from drifting: it was written first and immediately named twenty-four roles whose audit entry contradicted their own metadata, nine of them shipping an adapter while the list still called them untried candidates.

### native_server (1)

`web-app-homeassistant`.

### native_client (4)

`web-app-flowise`, `web-app-hermes`, `web-app-openclaw`, `web-app-openwebui`.

### native_both (1)

`web-app-n8n`.

### plugin_server (2)

`web-app-moodle`, `web-app-wordpress`.

### adapter_server (16)

`svc-db-qdrant`, `web-app-baserow`, `web-app-checkmk`, `web-app-fider`, `web-app-gitea`, `web-app-gitlab`, `web-app-jellyfin`, `web-app-jenkins`, `web-app-listmonk`, `web-app-mattermost`, `web-app-nextcloud`, `web-app-pretix`, `web-app-prometheus`, `web-app-snipe-it`, `web-app-zammad`, `web-svc-libretranslate`.

### blocked (11)

An upstream path exists or is claimed, and something concrete stops it here. Each row names what, using the reason vocabulary above, so "blocked" never reads as "nobody looked".

`svc-ai-litellm`, `svc-ai-lmstudio`, `svc-db-elasticsearch`, `svc-db-mariadb`, `svc-db-redis`, `web-app-discourse`, `web-app-erpnext`, `web-app-matomo`, `web-app-odoo`, `web-app-penpot`, `web-app-shopware`.

| role | reason | blocker |
| --- | --- | --- |
| `svc-ai-litellm` | `version_unverified` | The pinned release is inference-only; an MCP-capable one may be selected only after source inspection proves per-server routes, exact tool allowlists and the credential lifecycle. |
| `svc-ai-lmstudio` | `version_unverified` | The image is an unversioned preview; an explicit MCP-capable headless version has to replace it before a surface can be curated. |
| `svc-db-elasticsearch` | `missing_dependency` | The maintained native path needs Kibana Agent Builder with its index privileges and licence; the older sidecar is deprecated. |
| `svc-db-mariadb` | `shared_engine_isolation` | A global MCP server would attach to the shared engine; the alternative is one sidecar per consuming application with a database-scoped read-only principal. |
| `svc-db-redis` | `stdio_only` | The upstream server is stdio-oriented and broadly mutating over a cache several applications share. |
| `web-app-discourse` | `stdio_only` | The project-owned server passes ownership, licence, pinning and read-only default, but its HTTP transport serves one session per process, which upstream asserts in `src/test/transport.test.ts` at `v0.3.1`; the deploy probe alone would leave it restart-required. |
| `web-app-erpnext` | `version_unverified` | The Frappe MCP component is experimental and unverified against the pinned Frappe v16. |
| `web-app-matomo` | `unreviewed_third_party` | The project-owned plugin is unaudited: endpoint, transport, auth and tool scope are unverified in source. |
| `web-app-odoo` | `unreviewed_third_party` | Neither Odoo SA nor the OCA publishes a server; the leading third party carries 197 of 231 commits from one author, keeps its access control in a separate Odoo Apps store module outside any pinnable tag, and defaults to a mutating tool scope. |
| `web-app-penpot` | `interactive_browser_session` | The server needs an active browser tab and plugin connection, and can execute powerful design-context operations. |
| `web-app-shopware` | `version_unverified` | The pinned 6.7.8.2 predates the experimental native `/api/_mcp` server. |

### adapter_candidate (38)

An adapter could reach these, and none has been curated yet. The five that used to sit under "current MCP metadata requiring revalidation" are here because that revalidation found no shipped surface to revalidate.

`svc-db-typesense`, `web-app-akaunting`, `web-app-bigbluebutton`, `web-app-bluesky`, `web-app-bookwyrm`, `web-app-bridgy-fed`, `web-app-confluence`, `web-app-decidim`, `web-app-espocrm`, `web-app-friendica`, `web-app-funkwhale`, `web-app-jira`, `web-app-jitsi`, `web-app-joomla`, `web-app-kix`, `web-app-magento`, `web-app-mailu`, `web-app-mastodon`, `web-app-matrix`, `web-app-mediawiki`, `web-app-minio`, `web-app-mobilizon`, `web-app-opencloud`, `web-app-openproject`, `web-app-opentalk`, `web-app-peertube`, `web-app-pihole`, `web-app-pixelfed`, `web-app-postmarks`, `web-app-seaweedfs`, `web-app-semaphore`, `web-app-socialhome`, `web-app-suitecrm`, `web-app-taiga`, `web-app-xwiki`, `web-app-yourls`, `web-svc-api`, `web-svc-xmpp`.

Each candidate starts with three to five named read tools rather than a generated copy of an API, and the first investigation uses the starter contract recorded in [Adapter starter contracts](#adapter-starter-contracts). If the exact pinned version cannot implement the named contract through a stable authenticated API, the role becomes `blocked` with the observed reason rather than receiving a generic substitute.

### enabler (2)

`svc-ai-mcp-adapter`, `web-app-keycloak`.

`svc-ai-mcp-adapter` carries no MCP surface of its own. It is the adapter runtime a provider role instantiates, so its disposition is `enabler` and it never appears in discovery as a provider or a consumer.

### subordinate (2)

`web-svc-collabora`, `web-svc-onlyoffice`.

These are reached through the owning document application's MCP boundary, such as Nextcloud or OpenCloud, rather than receiving a second independent service-account tool surface.

### no_surface (99)

These roles stay out of shared MCP discovery.
A future exception requires a new record with a fixed operation list, dedicated identity, isolation boundary, human approval for mutations, and audit trail.

**`host_execution_boundary` (47):** `dev-arduino`, `dev-core`, `dev-java`, `dev-locales`, `dev-make`, `dev-nix`, `dev-nodejs`, `dev-python`, `drv-epson-multiprinter`, `drv-intel`, `drv-lid-switch`, `drv-non-free`, `dsk-base`, `dsk-bluray-player`, `dsk-chromium`, `dsk-code`, `dsk-copyq`, `dsk-docker`, `dsk-dotlinker`, `dsk-firefox`, `dsk-git`, `dsk-gnome`, `dsk-gnome-caffeine`, `dsk-gnome-extensions`, `dsk-gnome-terminal`, `dsk-gnt-claude`, `dsk-gnt-codex`, `dsk-gnt-cursor`, `dsk-gnt-pi`, `dsk-gnucash`, `dsk-jrnl`, `dsk-keepassxc`, `dsk-laya`, `dsk-libreoffice`, `dsk-micro`, `dsk-neovim`, `dsk-nextcloud`, `dsk-obs`, `dsk-qbittorrent`, `dsk-retroarch`, `dsk-spotify`, `dsk-ssh`, `dsk-torbrowser`, `dsk-virtualbox`, `dsk-zoom`, `gen-hunspell`, `user-workstation`.
These roles operate a workstation, developer toolchain, device, or host package; bridging them would amount to shared shell, filesystem, browser-session, device, or host execution without an application-specific remote identity.
`dsk-base` and `user-workstation` provision the login account the other desktop roles write for, which is the host execution boundary itself rather than an application behind it.

**`privileged_control_plane` (27):** `svc-ai-agent-broker`, `svc-ai-jupyter`, `svc-bkp-local-2-device`, `svc-bkp-nfs-2-local`, `svc-bkp-remote-2-local`, `svc-bkp-secrets-2-local`, `svc-bkp-volume-2-local`, `svc-dns-unbound`, `svc-net-firewall`, `svc-net-tor`, `svc-net-wireguard-core`, `svc-net-wireguard-firewalled`, `svc-net-wireguard-plain`, `svc-opt-keyboard-color`, `svc-opt-ssd-hdd`, `svc-opt-swapfile`, `svc-prx-openresty`, `svc-registry-cache`, `svc-registry-docker`, `svc-runner`, `svc-storage-nfs-client`, `svc-storage-nfs-server`, `svc-swarm-manager`, `svc-swarm-node`, `svc-virt-kata`, `update`, `web-app-openbao`.
These roles can recover secrets, alter routing or host state, run code, change deployment state, or reach storage/control-plane sockets; they require a separate audited operations gateway and human approval rather than general-purpose application MCP.

**`shared_engine_isolation` (4):** `svc-db-memcached`, `svc-db-openldap`, `svc-db-postgres`, `svc-db-rabbitmq`.
A generic endpoint would bypass application and tenant authorization on a shared engine.
Any future exception requires a provider-application-specific account, namespace/database/schema/queue restriction, fixed named operations, and no engine administrator credential.

**`administrative_surface` (5):** `web-app-fusiondirectory`, `web-app-lam`, `web-app-pgadmin`, `web-app-phpldapadmin`, `web-app-phpmyadmin`.
These UIs expose identity or database administration rather than a bounded application-domain API and are never represented by a shared service-account tool surface.

**`duplicate_owner` (1):** `web-app-litellm`.
This role is only the UI of the separately classified LiteLLM service role, which owns any future MCP gateway contract.

**`no_remote_surface` (27):** `svc-ai-ollama`, `svc-ai-robot`, `svc-ai-s1`, `svc-ai-searxng`, `svc-ai-tika`, `web-app-chess`, `web-app-dashboard`, `web-app-docs`, `web-app-fediwall`, `web-app-hugo`, `web-app-littlejs`, `web-app-mig`, `web-app-mini-qr`, `web-app-navigator`, `web-app-roulette-wheel`, `web-opt-rdr-domains`, `web-opt-rdr-www`, `web-svc-asset`, `web-svc-cdn`, `web-svc-coturn`, `web-svc-css`, `web-svc-file`, `web-svc-html`, `web-svc-legal`, `web-svc-logout`, `web-svc-mirror`, `web-svc-simpleicons`.
These roles have no independently useful authenticated remote action contract at the pinned implementation.
Static published content may later be consumed through one owning application's bounded `resource_readonly` adapter, but a new MCP sidecar that merely reimplements a static site's behaviour does not count as integration.
Model tool calling in Ollama does not by itself make Ollama an MCP client or server.

## Consequences ⚖️

### What the decision cost

Instantiating per provider means the adapter is deployed as many times as there are surfaces, each with its own credential, network attachment and endpoint. That is the price of the boundary: a shared instance would be one process to run and one credential to steal.

Requiring a disposition for every role turned a silent default into 172 explicit decisions that a lint now keeps current. A new role fails that lint until somebody disposes of it, which is the intended friction.

Declaring every adapter field explicitly means a surface cannot be enabled by adding one flag. Eight of the enabled serving surfaces reached that bar; the remaining thirty-eight candidates did not, and the audit says so rather than shipping them with defaults.

### What enforcing it found

The rules were written first and the code audited against them afterwards. Each of the following was live at the time it was found, not a hypothetical the design ruled out:

- **Nextcloud minted a new app password on every run and revoked none.** The name was fixed and managed, so each run that found the stored password rejected added another valid token to the account while every previous one kept full access. The mint is now preceded by a listing and the revocation of every token carrying that name.
- **Qdrant ran with no authentication at all.** Its environment set the HTTP port and disabled telemetry, so every container reaching its network held full read, write and delete access to every collection, and the surface's read-only promise rested entirely on the adapter's contract naming only GET routes. The engine now declares `read_only_api_key`, the adapter presents it, and a write route is refused by the engine rather than only by the adapter.
- **The adapter leaked its upstream credential on a redirect.** It opened the upstream with `urlopen`, which follows redirects, and urllib copies the original request's headers onto the target, so an upstream answering `302` with an off-host location would have handed the credential to whoever it named. The opener now refuses redirects outright, since the target is contracted.
- **Published tool schemas were a suggestion, not a boundary.** An argument the contract does not name was appended to the upstream request as a query parameter, and a tool declaring no schema accepted anything. Arguments are now validated against the contract, after the size ceiling so a large payload is still refused for being large.
- **Prometheus ran with no `--query.timeout`**, so a query the adapter abandoned after 15s kept the server busy for its two-minute default, and a range query's point count was unbounded although the response was truncated to 100 rows. The timeout is now derived from `mcp.limits.timeout_seconds`, and `policy.assert_range` refuses a range whose point count exceeds the contract's `result_items`, naming the smallest step that would fit.
- **n8n shipped with no `allowed_groups` while declaring an `mcp` role nothing consulted**, and minted a public-API key per run that it then left standing. The gate is closed and the key is revoked before the run ends.
- **Flowise's published images do not contain the version their tag claims:** `3.1.3`, `3.1.4` and `latest` all ship `flowise` 3.1.2, because upstream's Dockerfile runs an unpinned `npm install -g flowise` whose layer the release CI reuses. The role builds from an explicit npm pin and verifies the served route set.
- **Two proofs were vacuous.** Flowise tool-name verification compared against a hardcoded empty list, and every role-local MCP spec gated itself on the service flag, so a surface that kept serving after being switched off was indistinguishable from one never deployed. Both now fail when they should.
- **Twenty-four roles' audit entries contradicted their own metadata** the first time the classification lint ran, nine of them shipping an adapter while the list called them untried candidates.

### What it does not yet hold

- Credentials are kept out of logs, task output and Playwright traces by three static lints. Generated non-secret configuration needs a secret/non-secret classification of rendered files that does not exist; API responses and exception text are runtime observations.
- Endpoint DNS and routing from each client, in compose and in swarm, is unproven; only a running cluster can show it. The isolation half is covered, by a probe that compares the sidecar's own addresses against the declared subnets.
- No client executes a deterministic real tool call in every deployment. Flowise does, through its managed Agentflow fixture; the others assert less.
- The adapter `digest` pins nothing. All ten `implementation: adapter` roles carry the identical placeholder `sha256:` followed by sixty-four zeros, the schema only checks that prefix, and the running image is resolved through `lookup('container_image', …)` instead. A lint that rejects the placeholder has to land together with real digests rather than before them.
- Per-pair networks have to replace `kind: mcp_client`, which opens a provider to every client rather than to the admitted one. Either the sidecar joins only the pair network and the provider joins it too, or the isolation check becomes an identity check over the admitted peers rather than a count.
- Hermes renders its agent config and its env from two evaluations of one discovery list, and they disagree: the config carried `Bearer ${env:WEB_APP_PROMETHEUS_MCP_TOKEN}` while the env defined no `*_MCP_TOKEN`, so the client presented an empty bearer and the adapter correctly answered `401`. Any fix has to make both render from one evaluation.
- Mutating variants have no tests, because no surface enables mutations. The gate exists instead: a role setting `tools.mutating_tools_enabled` without an `mcp.mutating_proofs` block naming an existing artifact for each of the five proofs fails lint.

### Remaining rollout

Qdrant and the high-value read adapters are in place. What is left, in order: the remaining business, content, social and operations adapters, once the shared contract and the first adapters pass compose and swarm tests; and separately reviewed evaluations of the Shopware upgrade, the ERPNext plugin, the Matomo plugin, the LiteLLM gateway and the LM Studio client, because each moves an upstream version or maturity boundary.

## Adapter starter contracts

These are proposed repository contracts for the `adapter_candidate` roles, not claims that upstream already uses these names.

| Family | Roles | Initial permitted surface | Mandatory additional guard |
|---|---|---|---|
| Search and observability | `svc-db-typesense`, `web-app-checkmk`, `web-app-prometheus` | Collection search; host/service status; PromQL query, query range, labels, metadata, and targets | Per-application collection/index, explicit lookback and sample caps, no configuration or administration endpoint |
| Content and storage | `web-app-bookwyrm`, `web-app-funkwhale`, `web-app-jellyfin`, `web-app-joomla`, `web-app-mediawiki`, `web-app-minio`, `web-app-opencloud`, `web-app-peertube`, `web-app-seaweedfs`, `web-app-xwiki`, `web-svc-libretranslate` | Catalog/page/library search and get; S3 list/head/get; translate and detect | User or service identity restricted to the intended library/site/bucket/prefix; no edit/upload/delete by default |
| Business applications | `web-app-akaunting`, `web-app-decidim`, `web-app-espocrm`, `web-app-fider`, `web-app-kix`, `web-app-listmonk`, `web-app-magento`, `web-app-pretix`, `web-app-snipe-it`, `web-app-suitecrm`, `web-app-taiga`, `web-app-yourls`, `web-app-zammad` | Named list, search, and get tools for the application's primary records | Dedicated role with field/tenant restrictions; no generic CRUD, no arbitrary filter language, and no Adobe Commerce claim for Magento Open Source |
| Federated social and messaging | `web-app-bluesky`, `web-app-bridgy-fed`, `web-app-friendica`, `web-app-mailu`, `web-app-mastodon`, `web-app-matrix`, `web-app-mobilizon`, `web-app-pixelfed`, `web-app-postmarks`, `web-app-socialhome`, `web-svc-xmpp` | Search or read public/user-visible content and account state | Per-user token is required for private feeds, rooms, messages, or mail; a shared service account never merges users' private data |
| High-side-effect operations | `web-app-bigbluebutton`, `web-app-jitsi`, `web-app-opentalk`, `web-app-pihole`, `web-app-semaphore` | Meeting/status/job/log reads only | Create/end meeting, DNS blocking changes, playbook/Terraform/shell execution, and configuration changes require a separate role, human confirmation, idempotency key, and audit event |

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
| `web-app-postmarks` | `resource_readonly` | `postmarks_search_public_bookmarks`, `postmarks_get_public_bookmark`, `postmarks_get_public_feed` | Public collection only; the single owner secret is never exposed to a shared client |
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

## Upstream sources

An upstream README or current default branch may identify a candidate, but only the source and tests of the exact selected tag or digest close a compatibility question.

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
