# MCP User Delegation 🪪

`auth_subject: user` and `auth: oidc` claim that an MCP call executes with the
requesting end user's permissions. A `delegation:` block records the audit that
backs the claim; without it,
[`test_mcp_schema.py`](../../../../../../tests/lint/ansible/services/test_mcp_schema.py)
rejects the role.

## Declaring it

```yaml
mcp:
  auth: oidc
  auth_subject: user
  delegation:
    verified_version: 1.2.3
    source_url: https://example.invalid/project/tree/v1.2.3/path/to/auth
    refresh: true
    revocation: true
    audience_binding: true
```

All three booleans MUST be `true`, and `verified_version` MUST name the exact
tag or digest the source was read at. A newer upstream release is not evidence
for the deployed pin.

## Client audit

| Client | Pin | Delegation | Evidence |
|---|---|---|---|
| `web-app-openwebui` | 0.11.0 | capable | `ToolServerConnection.auth_type: system_oauth` resolves the caller's token through `oauth_manager.get_oauth_token(user.id, oauth_session_id)` and presents it as the Bearer |
| `web-app-hermes` | v2026.7.20 | incapable | [`config.yaml.j2`](../../../../../../roles/web-app-hermes/templates/config.yaml.j2) renders one static `Authorization` header per server; no user session exists at render time |
| `web-app-openclaw` | 2026.7.1 | incapable | [`openclaw.json.j2`](../../../../../../roles/web-app-openclaw/templates/openclaw.json.j2) renders one static `Authorization` header per server |
| `web-app-flowise` | 3.1.3 | incapable | Registry entries bind to a workspace and store one encrypted custom header, not a per-user token |

## Provider audit

| Provider | Pin | Delegation | Evidence |
|---|---|---|---|
| `web-app-baserow` | 2.3.1 | incapable | The endpoint authenticates a Baserow app password bound to the endpoint owner |
| `web-app-gitea` | sidecar | incapable | The sidecar authenticates a Gitea token |
| `web-app-gitlab` | 18.x | incapable | The endpoint authenticates a GitLab PAT or GitLab-issued OAuth token, not a platform OIDC access token |
| `web-app-homeassistant` | 2026.7 | incapable | The endpoint authenticates a Home Assistant long-lived access token |
| `web-app-jenkins` | plugin | incapable | The endpoint authenticates Jenkins basic auth |
| `web-app-mattermost` | plugin | incapable | The endpoint authenticates a Mattermost bot token |
| `web-app-moodle` | plugin | incapable | The endpoint authenticates a Moodle web-service token |
| `web-app-nextcloud` | ExApp | incapable | The endpoint authenticates a Nextcloud app password bound to one user |

No pair of a capable client and a capable provider exists at the current pins,
so every provider declares `auth_subject: service_account`.

## The renderable path

`svc-ai-mcp-adapter` validates the platform's OIDC access token, so an
adapter-backed provider is the one surface that can declare
`auth: oidc` with `auth_subject: user`. Only Open WebUI can consume it:

- [`mcp_authorization`](../../../../../../plugins/filter/mcp/authorization.py)
  raises for `auth: oidc`, because a rendered config cannot carry a caller's
  token, and `mcp_authorization_is_renderable` returns `false` so the
  static-config clients drop the server instead of presenting a wrong secret.
- [`mcp_tool_server_connections`](../../../../../../plugins/filter/mcp/tool_server_connections.py)
  emits `auth_type: system_oauth` with an empty `key` for those servers, so
  Open WebUI resolves the caller's own token per request.

## See Also

- Service block vocabulary: [mcp.md](../mcp.md)
