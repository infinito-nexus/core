# MCP Service Block 🔌

A role declares `meta/mcp.yml` when it actually serves or consumes MCP. The file is a capability descriptor, not a service entry: no single role provides MCP, so the service registry cannot pair provider and consumer, and the `mcp_consumer` flag in `meta/services.yml` does it instead. Vocabulary lives in [`utils/roles/applications/mcp.py`](../../../../../utils/roles/applications/mcp.py); the hard lint is [`test_mcp_schema.py`](../../../../../tests/lint/ansible/services/test_mcp_schema.py).

`classification` is required and is one of `native_server`, `native_client`, `native_both`, `plugin_server`, `sidecar_server`, `adapter_server`. A role that cannot serve declares no `mcp` block at all.

## Server shape

```yaml
mcp:
  bond: 1
  enabled: true
  shared: true
  classification: native_server
  direction: server            # server | client | both
  transport: sse               # streamable_http | sse
  exposure: internal           # internal | public
  auth: app_password           # oidc | app_password | basic_auth | bearer_token | upstream_session | none
  auth_subject: service_account  # user | service_account | administrator | none
  implementation: native       # native | plugin | sidecar | adapter | external
  credential:
    owner: mcp-web-app-example # a dedicated non-login identity, never `administrator`
    source: token_store        # token_store | credentials
    key: web-app-example
  endpoint:
    service_key: example       # names a service entry in the same file
    path: /mcp
    port_key: http             # resolves under that service's ports.local or ports.internal
  tools:
    read_only_default: true
    mutating_tools_enabled: false
```

`exposure: public` additionally requires a complete `limits` block.

## Client shape

A client declares what it can present instead of what it serves:

```yaml
mcp:
  classification: native_client
  direction: client
  implementation: native
  supported_transports: [streamable_http, sse]
  supported_auths: [bearer_token, app_password, upstream_session]
```

A client-only block MUST NOT declare an `endpoint`.

## Adapter shape

`implementation: adapter` requires `classification: adapter_server` and a pinned, hash-checked contract:

```yaml
  adapter:
    type: openapi_allowlist    # see below
    image: registry.example.invalid/infinito-mcp-adapter
    version: 1.2.3
    digest: sha256:0123456789abcdef
    upstream_api_version: v1
    specification_path: roles/web-app-example/files/mcp/openapi-v1.json
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
    allowlist: [example_search, example_get]
    schema_sha256: sha256:abcdef0123456789
    read_only_default: true
    mutating_tools_enabled: false
```

`type` is one of `openapi_allowlist`, `graphql_allowlist`, `named_query`, `s3_prefix`, `prometheus_readonly`, `n8n_workflow`, `resource_readonly`. `graphql_allowlist`, `named_query`, `s3_prefix` and `resource_readonly` additionally require a non-empty `adapter.scope` naming the exact buckets, prefixes, collections or queries reachable. `openapi_allowlist` and `graphql_allowlist` require a checked-in `specification_path` under the role's own `files/`.

## Rules

- `classification` is required and MUST be deployable; all MCP-specific fields MUST be literals (only `enabled`/`shared` may carry Jinja).
- `enabled`/`shared` MUST NOT name a peer role. Provider enablement is explicit operator or variant state; the variant axis lives in `meta/variants.yml`.
- `direction: server | both` requires `auth`, `credential`, a complete `endpoint`, and at least one admitted client.
- Admission lives in `meta/services.yml`, not here. A client sets `services.<own-entity>.mcp_consumer: true` in its own role; a provider refuses one by setting `mcp_consumer: false` on that client's entry. [`test_mcp_consumer_services_entry.py`](../../../../../tests/lint/ansible/services/test_mcp_consumer_services_entry.py) requires every provider to carry a `"{{ '<client>' in group_names }}"`-gated entry for every declared client, so a round plans provider and client together.
- `credential.owner` MUST NOT be `administrator`. Two providers resolving to the same owner and secret abort discovery.
- `auth: none` requires `exposure: internal`.
- `auth_subject: service_account | administrator` requires an explicit `tools.mutating_tools_enabled: false`.
- `auth_subject: user` or `auth: oidc` requires a `delegation` block; see [delegation.md](mcp/delegation.md).
- `endpoint.service_key` MUST name a service in the same file; `endpoint.port_key` MUST resolve under its `ports.local` or `ports.internal`.
- Suppress a finding with `# nocheck: mcp-schema` (file head = whole file, on/above a line = that finding).

## Public exposure

`exposure: public` puts the endpoint on the role's own vhost, so it inherits what that vhost already provides: routing through the shared proxy, TLS from the platform certificate, `client_max_body_size` from `server.client_max_body_size`, and the proxy read timeout of the location it is mounted in.

Rate limiting is not among them. The proxy ships no `limit_req` or `limit_conn` anywhere, so a public MCP endpoint is only as protected as its own authentication and its declared `limits`. An operator exposing one to the open internet has to put a rate limiter in front of the vhost; the platform will not supply one.

Prefer `exposure: internal`. A client inside the container network reaches the endpoint without any of this.

## Why stdio is not deployed

`transport` accepts `streamable_http` and `sse` only. A stdio MCP server is a local process the client spawns, so it inherits the client container's filesystem and network with no endpoint to authenticate, no proxy to route through, and nothing for a probe to reach. Every property the other rules rely on (`auth`, `exposure`, `endpoint`) is undefined for it. Clients that support stdio are pinned away from it in their own role: Flowise sets `CUSTOM_MCP_PROTOCOL=sse` so no flow can spawn a command.

## Client discovery

Clients do not read the server list directly. [`lookup('mcp_servers')`](../../../../../plugins/lookup/mcp_servers.py) computes the intersection of the provider's admitted clients, resolved by `derive_allowed_consumers` in [`utils/roles/applications/mcp.py`](../../../../../utils/roles/applications/mcp.py), with the calling client's `supported_transports` and `supported_auths`, resolves each provider's declared credential, and returns:

```yaml
MCP_DISCOVERY: "{{ lookup('mcp_servers') }}"
MCP_DISCOVERED_SERVERS: "{{ MCP_DISCOVERY.selected }}"
MCP_REJECTED_SERVERS: "{{ MCP_DISCOVERY.rejected }}"
```

Every rejected entry carries a stable `reason`: `consumer_not_allowed`, `transport_unsupported`, `auth_unsupported`, `credential_missing` or `endpoint_unreachable`.

## RBAC

Reaching a tool server is a distinct grant from using the application, carried by the provider's `mcp` RBAC role. `mcp` is application-scoped: it is granted through `application_roles`, never through the unscoped `roles` list, so granting it on one application grants it nowhere else.

```yaml
users:
  alice:
    application_roles:
      web-app-baserow: [mcp]
```

## See Also

- Service metadata basics: [base.md](base.md)
- User delegation audit: [delegation.md](mcp/delegation.md)
