# MCP Service Block 🔌

A role with a Model Context Protocol surface declares one `mcp:` entry in `meta/services.yml`. The block carries the standard consumer flags plus MCP-specific fields. Vocabulary lives in [`utils/roles/applications/services/mcp.py`](../../../../../utils/roles/applications/services/mcp.py); the hard lint is [`tests/lint/ansible/services/test_mcp_schema.py`](../../../../../tests/lint/ansible/services/test_mcp_schema.py).

## Shape

```yaml
mcp:
  bond: 1
  enabled: false
  shared: false
  direction: server        # server | client | both
  transport: streamable_http  # streamable_http | sse
  exposure: internal       # internal | public
  auth: bearer_token       # oidc | app_password | basic_auth | bearer_token | upstream_session | none
  auth_subject: user       # user | service_account | administrator | none
  implementation: native   # native | plugin | sidecar | external
  endpoint:                # required for direction: server | both
    service_key: baserow   # names a service entry in the same file
    path: /mcp
    port_key: http         # resolves under that service's ports.local or ports.internal
  tools:
    read_only_default: true
    mutating_tools_enabled: false
```

## Rules

- `direction` is required; all MCP-specific fields MUST be literals (only `enabled`/`shared` may carry Jinja).
- `direction: server | both` requires `auth` and a complete `endpoint` (`service_key`, `path`, `port_key`).
- `auth: none` requires `exposure: internal`.
- `auth_subject: service_account | administrator` requires an explicit `tools.mutating_tools_enabled: false`; omitting the key is rejected, because a privileged subject must state its tool policy rather than inherit a default. The field records the intent; where upstream exposes mutating tools unconditionally, the role README names the missing enforcement.
- `endpoint.service_key` MUST name a service in the same file; `endpoint.port_key` MUST resolve under its `ports.local` or `ports.internal`.
- Suppress a finding with `# nocheck: mcp-schema` (file head = whole file, on/above a line = that finding).

## Public exposure

`exposure: public` puts the endpoint on the role's own vhost, so it inherits
what that vhost already provides: routing through the shared proxy, TLS from the
platform certificate, `client_max_body_size` from `server.client_max_body_size`,
and the proxy read timeout of the location it is mounted in.

Rate limiting is not among them. The proxy ships no `limit_req` or `limit_conn`
anywhere, so a public MCP endpoint is only as protected as its own
authentication. An operator exposing one to the open internet has to put a rate
limiter in front of the vhost; the platform will not supply one.

Prefer `exposure: internal`. A client inside the container network reaches the
endpoint without any of this, which is why five of the eight server roles stay
internal and only those whose upstream mounts MCP under the application's own
public routes are public.

## Why stdio is not deployed

`transport` accepts `streamable_http` and `sse` only. A stdio MCP server is a
local process the client spawns, so it inherits the client container's
filesystem and network with no endpoint to authenticate, no proxy to route
through, and nothing for a probe to reach. Every property the other rules rely
on (`auth`, `exposure`, `endpoint`) is undefined for it. Clients that support
stdio are pinned away from it in their own role: Flowise sets
`CUSTOM_MCP_PROTOCOL=sse` so no flow can spawn a command.

## Client discovery

Client roles discover server-capable roles through the `roles_with_service` lookup with the `direction` kwarg:

```yaml
{{ lookup('roles_with_service', 'mcp', direction='server') }}
```

Each returned entry carries `id`, `canonical_domain`, `canonical_url`, `iframe`, plus `transport`, `auth`, `auth_subject` and `endpoint` (`service_key`, `path`, resolved `port`). Callers that omit `direction` keep the original 4-key entries.

## See Also

- Service metadata basics: [base.md](base.md)
