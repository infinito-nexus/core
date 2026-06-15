# 025 - MCP Role Integration

## User Story

As a platform administrator of Infinito.Nexus, I want every role with a documented Model Context Protocol (MCP) surface to expose or consume MCP through the platform's standard service, identity, proxy, and test contracts so that AI clients can use application data and actions safely without one-off per-role wiring.

## Background

MCP is a client-server protocol for connecting AI hosts to external tools, resources, and prompts.
Several roles in this repository already deploy applications whose upstream projects document MCP support, but the current role tree has no MCP configuration or tests.
A repository scan for `mcp` returns no role-local implementation, so this requirement starts from a clean integration layer rather than from an existing partial contract.

The integration MUST distinguish two directions:

- MCP server roles expose application capabilities through an authenticated MCP endpoint.
- MCP client roles connect to enabled MCP servers and present their tools to users through an AI surface.

The implementation MUST prefer native upstream MCP support.
Plugin, sidecar, or marketplace MCP servers MAY be used only when the upstream project documents them as supported or when the role README documents the risk and the operator explicitly enables the integration.

## Confirmed Decisions

These choices are settled at requirement creation time and bound the implementation. Re-opening any of them MUST be recorded in the implementing PR.

1. **Implementation precedence.** `native` > `plugin` > `sidecar` > `external`. A lower-precedence path is allowed only when the higher one is unavailable upstream and the role README documents why.
2. **Discovery reuses existing infrastructure.** Client roles discover servers through the existing [`roles_with_service`](../../plugins/lookup/roles_with_service.py) lookup (backed by `utils.cache.applications.get_merged_applications`), extended to filter by `services.mcp.direction` and to surface endpoint metadata. No new generated repository-wide application dictionary is introduced.
3. **Secrets reuse the credentials mechanism.** MCP tokens, app-passwords, and OAuth client secrets are declared in each role's [`meta/schema.yml`](../../roles/web-app-baserow/meta/schema.yml) `credentials:` block and read via `lookup('config', application_id, 'credentials.<name>')`. No new secret store is introduced.
4. **MCP state is a variant axis.** Roles that gain an MCP surface MUST express the enabled/disabled split through `meta/variants.yml` so CI matrix runs cover both states.
5. **Lint reuses the suppression model.** New MCP lint rules live under [`tests/lint/ansible/services/`](../../tests/lint/ansible/services/) and honour the existing `# nocheck:` marker convention (see [suppression docs](../contributing/actions/testing/suppression.md)).
6. **First slice.** The first end-to-end slice is `web-app-baserow` (server) plus `web-app-openwebui` (client).
7. **Audit artifact.** The repository-wide MCP audit is committed as `docs/requirements/025-mcp-role-integration-audit.yml` with one top-level `roles:` mapping keyed by role id.
8. **Every MCP implementation ships a Playwright test.** Each role that gains an MCP surface MUST add a matching Playwright spec under `roles/<role>/files/playwright/` that exercises its MCP surface (a server role's authenticated endpoint, a client role's configured-server list). No MCP role is considered implemented until its Playwright test is present and green.
9. **Authorization subject.** MCP integrations prefer user-scoped authorization. Service-account or administrator-scoped MCP credentials are allowed only for read-only default tool sets, or when the role README documents the upstream limitation and the operator explicitly enables mutating tools.

## Initial Upstream Survey

The following roles have an MCP surface confirmed from upstream or project-owned documentation at requirement creation time.
Each row is an implementation candidate, not proof that the current role already exposes MCP.

| Role | MCP direction | Source | Initial notes |
|---|---|---|---|
| [web-app-openwebui](../../roles/web-app-openwebui/) | Client | [Open WebUI MCP docs](https://docs.openwebui.com/features/extensibility/mcp/) | Native MCP client support requires Open WebUI `v0.6.31+` and uses Streamable HTTP. The role currently pins `version: main`, which MUST be replaced with an explicit MCP-capable tag before MCP is enabled. |
| [web-app-flowise](../../roles/web-app-flowise/) | Client | [Flowise Tools and MCP](https://docs.flowiseai.com/tutorials/tools-and-mcp) | Flowise supports Custom MCP. Production deployment MUST NOT enable arbitrary stdio commands by default. |
| [web-app-nextcloud](../../roles/web-app-nextcloud/) | Server | [Nextcloud Context Agent docs](https://docs.nextcloud.com/server/latest/admin_manual/ai/app_context_agent.html) | The Context Agent app exposes an MCP endpoint below the Nextcloud AppAPI proxy and uses app-password authentication. |
| [web-app-gitlab](../../roles/web-app-gitlab/) | Server | [GitLab MCP server docs](https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server/) | GitLab's MCP server is beta and tier-gated to Premium or Ultimate. The role uses GitLab EE, so licensing MUST be operator-gated. |
| [web-app-mattermost](../../roles/web-app-mattermost/) | Server | [Mattermost MCP Server docs](https://docs.mattermost.com/agents/mcpserver/README.html) | The production-safe path MUST follow Mattermost's documented Agents and MCP deployment guidance. |
| [web-app-openproject](../../roles/web-app-openproject/) | Server | [OpenProject MCP Server docs](https://www.openproject.org/docs/system-admin-guide/integrations/mcp-server/) | OpenProject documents an MCP endpoint under `/mcp` and OAuth application setup. |
| [web-app-baserow](../../roles/web-app-baserow/) | Server | [Baserow MCP Server docs](https://baserow.io/user-docs/mcp-server) <!-- nocheck: url — page is live (HEAD+GET 200); baserow.io edge intermittently 404s CI runner IPs --> | Baserow documents a native built-in MCP server. |
| [web-app-jenkins](../../roles/web-app-jenkins/) | Server | [Jenkins MCP Server plugin](https://plugins.jenkins.io/mcp-server/) | Jenkins support is plugin-based and MUST be pinned like other Jenkins plugins. |
| [web-app-moodle](../../roles/web-app-moodle/) | Server | [Moodle MCP plugin](https://moodle.org/plugins/webservice_mcp) | Moodle support is plugin-based and MUST be version-compatible with the pinned Moodle LTS release. |
| [web-app-gitea](../../roles/web-app-gitea/) | Server | [Gitea MCP package](https://pkg.go.dev/gitea.com/gitea/gitea-mcp) | Gitea support appears as a project-owned MCP package. The implementation MUST verify release, packaging, and auth maturity before enabling it. |

The following roles are known follow-up audit items because a cloud-only, third-party, or ambiguous MCP path exists but is not enough to enable a self-hosted role automatically:

- [web-app-jira](../../roles/web-app-jira/) and [web-app-confluence](../../roles/web-app-confluence/): Atlassian documents the [Rovo MCP Server](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/) for Atlassian Cloud. These roles deploy unsupported self-hosted containers, so they MUST remain out of scope unless a self-hosted MCP path is documented and operator-approved.
- [web-app-wordpress](../../roles/web-app-wordpress/): MCP is available through ecosystem plugins and hosted-provider tooling, but the implementation MUST choose a maintained plugin deliberately and MUST NOT install an arbitrary plugin by name without review.
- [web-app-odoo](../../roles/web-app-odoo/): MCP options appear to be third-party add-ons. The role MUST remain out of scope unless a maintained add-on is explicitly selected and reviewed.
- [web-app-discourse](../../roles/web-app-discourse/): an MCP repository exists, but Discourse community guidance has not been confirmed as a stable supported server contract. The role MUST be audited before any integration.

## Target Schema

### Shared MCP service flag

Every MCP-capable role MUST expose a role-local `mcp` service block in `meta/services.yml`.
The block MUST be absent from roles that have no MCP surface after the audit, unless a lint rule requires an explicit exemption.

```yaml
mcp:
  enabled: false
  shared: false
  direction: server        # server, client, or both
  transport: streamable_http
  exposure: internal       # internal by default; public requires explicit role documentation
  auth: oidc               # oidc, app_password, bearer_token, upstream_session, or none
  auth_subject: user        # user, service_account, administrator, or none
  implementation: native   # native, plugin, sidecar, or external
```

Rules:

- `enabled` MUST default to `false` in role defaults. Integrated roles MUST use variants to verify both `enabled=false` and `enabled=true` states.
- The MCP surface ships disabled by default and is independent of the host role's `lifecycle`: a `beta` host role MUST NOT imply that its MCP surface is stable. An MCP surface is only considered validated once its acceptance criteria are met end to end.
- `shared` MUST mean that other Infinito.Nexus roles MAY discover and consume the MCP endpoint through the applications lookup.
- `direction` MUST distinguish MCP clients from MCP servers so client roles can discover only server roles.
- `transport` MUST default to `streamable_http` for server deployments. Stdio MAY exist only for local development and MUST NOT be enabled in a deployed web role by default.
- `exposure` MUST default to `internal`. Public MCP endpoints MUST have explicit authentication, rate limiting, proxy coverage, and README documentation.
- `auth: none` MUST fail lint unless the endpoint is bound to localhost or an internal-only network and the role README documents why authentication is impossible upstream.
- `auth_subject` MUST be `user` where upstream supports per-user authorization. `service_account` and `administrator` MUST keep mutating tools disabled by default.

### MCP endpoint metadata

Server roles MUST publish enough metadata for client roles and tests to discover the endpoint.
The `endpoint` and `tools` keys below are part of the **same** role-local `mcp` block as the shared service flag above; the two snippets are split only for readability and MUST be merged into one `mcp:` mapping in `meta/services.yml`.

```yaml
mcp:
  endpoint:
    service_key: baserow   # references services.<service_key>
    path: /mcp
    port_key: http        # references services.<service_key>.ports.local.<key>
    health_path: /mcp
  tools:
    read_only_default: true
    mutating_tools_enabled: false
```

Rules:

- The endpoint path MUST be relative to the role's canonical HTTPS origin unless the role uses an internal-only sidecar.
- `service_key` MUST name an existing top-level service entry in the same `meta/services.yml`, and `port_key` MUST name an existing key under `services.<service_key>.ports.local`.
- For `implementation: native` exposed under `/mcp` on the role's existing HTTP port, no new port is added. For `implementation: sidecar` or `external`, the role MUST register a dedicated service entry and local port so the central collision check covers it, and MUST NOT reuse the application's primary HTTP port.
- Mutating tools MUST be disabled by default when upstream supports tool filtering or scopes.
- When mutating tools cannot be disabled, the integration MUST require explicit operator opt-in before `mcp.enabled=true`.

### Server metadata (`meta/server.yml`)

MCP changes the role's HTTP surface, so each server role MUST keep its [`meta/server.yml`](../../roles/web-app-baserow/meta/server.yml) contract consistent with the new endpoint.

Rules:

- **Routing.** MCP MUST be served from the role's existing `domains.canonical` origin under the `mcp.endpoint.path`. A dedicated MCP subdomain MUST NOT be added unless upstream cannot serve MCP under a path, in which case the new domain MUST be registered in `domains.canonical` and documented in the role README.
- **Status codes / health.** An authenticated MCP endpoint returns a non-2xx status (e.g. `401`/`406`) to unauthenticated probes. The role MUST NOT let the MCP path break the platform uptime/status-code check: either the health probe targets an unauthenticated `mcp.endpoint.health_path`, or the MCP path is excluded from the canonical `status_codes` check. The chosen approach MUST be explicit in `server.yml`.
- **Networks.** For `implementation: sidecar` or `external`, the MCP container MUST attach to the role's existing `networks.local` subnet and MUST NOT introduce a new top-level network.
- **CSP.** MCP Streamable HTTP runs server-to-server (the client role's backend connects to the server role), so a server role MUST NOT need a new browser `csp` `connect-src` entry for MCP. If an implementation does require a browser-side MCP fetch, the added `connect-src` source MUST be documented in the role README.

### MCP client discovery

Client roles such as `web-app-openwebui` and `web-app-flowise` MUST discover enabled shared MCP server roles through the merged applications data.
They MUST NOT hard-code the candidate list in templates.

The discovery path MUST reuse the existing [`roles_with_service`](../../plugins/lookup/roles_with_service.py) lookup rather than a new template-side scan. That lookup currently selects roles on `services.<name>.{enabled, shared}` and returns `{id, canonical_domain, canonical_url}`. For MCP it MUST be extended so that:

- selection additionally filters on server-capable roles (`direction: server` or `direction: both`), so client roles never offer a client-only role as a target;
- each returned entry also carries the endpoint metadata a client needs to connect, at least `service_key`, `path`, resolved port, `transport`, `auth`, and `auth_subject`, sourced from the role's `mcp.endpoint` block.

The lookup MUST remain backed by `utils.cache.applications.get_merged_applications` and MUST NOT introduce a generated repository-wide application dictionary.

## Acceptance Criteria

### Repository-wide audit

- [ ] A deterministic audit is exposed as a `make` target (e.g. `make mcp-audit`) backed by a test under `tests/`, so operators do not run a raw script; it enumerates every role under `roles/` and classifies MCP support as `native`, `plugin`, `sidecar`, `external-only`, or `none`.
- [ ] The committed audit artifact lives at `docs/requirements/025-mcp-role-integration-audit.yml` and uses `roles.<role_id>.{classification,source_url,minimum_version,direction,transport,auth,auth_subject,implementation,notes}`.
- [ ] The audit output lives outside `meta/services.yml`; a role with no MCP surface keeps its `services.yml` free of an `mcp` block rather than carrying an empty one, so the audit and the per-role schema do not duplicate each other.
- [ ] The audit output includes every role from the [Initial Upstream Survey](#initial-upstream-survey) and records the source URL, minimum version, direction, transport, auth model, authorization subject, and implementation type.
- [ ] Roles classified as `external-only` or `none` are documented in the audit output so future MCP sweeps can diff the classification.
- [ ] A grep for `mcp` before implementation is recorded in the implementing PR to show the baseline was empty.

### Shared contract

- [ ] [`docs/contributing/design/role/services/`](../contributing/design/role/services/) documents the `mcp` service block, its fields, defaults, and allowed values.
- [ ] Role-meta lint under [`tests/lint/ansible/services/`](../../tests/lint/ansible/services/) rejects invalid `services.mcp.direction`, `services.mcp.transport`, `services.mcp.exposure`, `services.mcp.auth`, `services.mcp.auth_subject`, and `services.mcp.implementation` values, and honours the `# nocheck:` suppression convention for documented exceptions.
- [ ] Role-meta lint rejects `services.mcp.enabled=true` when `services.mcp.auth=none` and `services.mcp.exposure` is not internal-only.
- [ ] Role-meta lint rejects `services.mcp.auth_subject` values of `service_account` or `administrator` unless `services.mcp.tools.mutating_tools_enabled=false`, or the role carries an explicit documented exception.
- [ ] The [`roles_with_service`](../../plugins/lookup/roles_with_service.py) lookup, extended for `direction in [server, both]` and endpoint metadata, returns the connection data client roles need for enabled shared MCP server roles, without adding a generated repository-wide application dictionary.

### Routing, health & networking (`meta/server.yml`)

- [ ] MCP is served under the role's existing `domains.canonical` origin at `mcp.endpoint.path`; any new MCP subdomain is justified by an upstream limitation and registered in `domains.canonical`.
- [ ] Enabling MCP does not break the platform uptime/status-code check: the health probe targets an unauthenticated `health_path` or the MCP path is explicitly excluded from the role's `status_codes` contract.
- [ ] `implementation: sidecar` or `external` MCP containers attach to the role's existing `networks.local` subnet and add no new top-level network.
- [ ] No MCP server role adds a browser `csp` `connect-src` entry unless a browser-side MCP fetch is required and documented in the role README.

### Security contract

- [ ] No deployed role launches arbitrary user-provided stdio MCP commands by default.
- [ ] Every MCP server endpoint is protected by OIDC, app-password, bearer-token, upstream-session auth, or an explicitly documented internal-only exception.
- [ ] MCP credentials (tokens, app-passwords, OAuth client secrets) are declared in the role's [`meta/schema.yml`](../../roles/web-app-baserow/meta/schema.yml) `credentials:` block and consumed via `lookup('config', application_id, 'credentials.<name>')`; they are never written into `README.md`, Playwright traces, or non-secret env vars.
- [ ] Every MCP server role documents whether MCP calls execute as the requesting user, a service account, or an administrator, and the implementation enforces that subject consistently.
- [ ] Client roles MUST NOT register service-account or administrator-scoped MCP servers as globally enabled default tools unless the server advertises read-only tools only.
- [ ] Public MCP exposure includes proxy routing, TLS, request-size limits, timeout limits, and rate-limit guidance.
- [ ] Mutating MCP tools are off by default where upstream supports filtering, scopes, or permission flags.
- [ ] Role READMEs document the data and action surface exposed to MCP clients.

### MCP server roles

- [ ] [web-app-baserow](../../roles/web-app-baserow/) exposes its native MCP server when `services.mcp.enabled=true`, keeps it authenticated, and verifies at least one read-only tool through an MCP client.
- [ ] [web-app-gitlab](../../roles/web-app-gitlab/) exposes GitLab MCP only when the operator confirms the required tier/license and the endpoint is reachable at the documented self-managed path.
- [ ] [web-app-gitea](../../roles/web-app-gitea/) either ships the project-owned MCP server with pinned packaging and authenticated access or is reclassified with a documented blocker.
- [ ] [web-app-jenkins](../../roles/web-app-jenkins/) installs and pins the MCP Server plugin, exposes only authenticated Jenkins tools, and documents the tool scope.
- [ ] [web-app-mattermost](../../roles/web-app-mattermost/) deploys the documented production-safe Mattermost MCP path and verifies that the endpoint respects Mattermost authentication.
- [ ] [web-app-moodle](../../roles/web-app-moodle/) installs a Moodle-version-compatible MCP plugin and verifies token-scoped access through Moodle web services.
- [ ] [web-app-nextcloud](../../roles/web-app-nextcloud/) installs and configures the required Nextcloud apps for Context Agent MCP and verifies the AppAPI proxy endpoint with app-password authentication.
- [ ] [web-app-openproject](../../roles/web-app-openproject/) exposes the `/mcp` endpoint behind the role's existing auth model and verifies OAuth application setup.

### MCP client roles

- [ ] [web-app-openwebui](../../roles/web-app-openwebui/) is pinned to an explicit `v0.6.31+` tag (replacing the current `version: main`) that supports native MCP and can register every enabled shared Streamable HTTP MCP server role.
- [ ] [web-app-flowise](../../roles/web-app-flowise/) can register every enabled shared Streamable HTTP MCP server role through Custom MCP without enabling arbitrary stdio execution in deployed environments.
- [ ] Client roles render MCP connection configuration from role metadata and secrets, not from hard-coded role names.
- [ ] Client roles expose an administrator-visible list of configured MCP servers in Playwright coverage.

### Ambiguous and external-only roles

- [ ] [web-app-jira](../../roles/web-app-jira/) and [web-app-confluence](../../roles/web-app-confluence/) remain disabled for MCP unless a self-hosted Atlassian MCP path is documented or the role explicitly integrates with Atlassian Cloud as an external connector.
- [ ] [web-app-wordpress](../../roles/web-app-wordpress/) is audited for a maintained MCP plugin and is integrated only after the plugin's update cadence, license, authentication, and tool scope are documented.
- [ ] [web-app-odoo](../../roles/web-app-odoo/) is audited for a maintained MCP add-on and is integrated only after the add-on's update cadence, license, authentication, and tool scope are documented.
- [ ] [web-app-discourse](../../roles/web-app-discourse/) is audited against current Discourse guidance before any MCP server is enabled.

### Tests

- [ ] Unit or integration tests validate the MCP service schema and reject unsafe defaults.
- [ ] Each role that gains an MCP surface expresses the enabled/disabled split as a `meta/variants.yml` axis so the CI matrix exercises both states.
- [ ] For each integrated MCP server role, a role-local or shared MCP smoke test confirms that the endpoint advertises tools only after authentication.
- [ ] For each integrated MCP client role, Playwright verifies that an administrator can see at least one configured MCP server when a server role is enabled.
- [ ] Every integrated MCP role (server or client) ships a matching Playwright spec under `roles/<role>/files/playwright/` covering its MCP surface, and that spec is green before the role's Acceptance Criterion is marked complete.
- [ ] A deployment with `services.mcp.enabled=false` for all roles has no MCP endpoint reachable from the public proxy.
- [ ] A deployment with one MCP server role and one MCP client role proves end-to-end tool discovery through the client UI.
- [ ] With `services.mcp.enabled=true`, the role's uptime/status-code check still passes, proving the authenticated MCP path does not regress health monitoring.

### Documentation

- [ ] Every integrated role README documents the MCP endpoint, auth model, default state, exposed tool categories, and how to disable MCP.
- [ ] The role service design docs link to the MCP contract and explain why stdio MCP is not enabled in deployed web roles by default.
- [ ] This requirement file is cross-linked from the implementing PR.

## Validation Apps

The implementation MUST validate the first end-to-end slice with one server role and one client role before sweeping the full candidate set.
The recommended first slice is `web-app-baserow` plus `web-app-openwebui` because both have documented MCP support and avoid license-gated enterprise features.

```bash
INFINITO_APPS="web-app-baserow web-app-openwebui" \
  make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

After the first slice is green, every integrated role MUST pass its role-local deploy path and any matrix variants affected by MCP.

## Prerequisites

Before starting implementation work, the agent MUST read [AGENTS.md](../../AGENTS.md) and follow all instructions in it.

## Implementation Strategy

1. Create the repository-wide MCP audit and close the classification for every role.
2. Add the shared `services.mcp` schema, the `tests/lint/ansible/services/` lint rules, and the design documentation.
3. Extend the `roles_with_service` lookup for `direction` filtering and endpoint metadata so client roles can discover servers.
4. Implement the smallest end-to-end server plus client slice, preferably `web-app-baserow` to `web-app-openwebui` (pinning Open WebUI to an MCP-capable tag and adding the `mcp` variant axis).
5. Add the shared MCP smoke-test helper and client-side Playwright coverage.
6. Sweep the remaining confirmed server roles one at a time, keeping each role's README, credentials schema, `meta/server.yml` routing/health, and variants aligned.
7. Revisit ambiguous roles only after the confirmed set is green.

## Commit Policy

- The shared schema and first end-to-end slice MAY land together.
- Each additional MCP server role SHOULD land in a focused commit or PR when it can be validated independently.
- The implementing PR MUST not mark any Acceptance Criterion complete until the behavior is verified end to end.
