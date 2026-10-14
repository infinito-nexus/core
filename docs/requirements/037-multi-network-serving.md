# 037 - Multi-Network Serving

## User Story

As an operator of an Infinito.Nexus node that runs the Tor provider next to a public clearnet domain, I want every web application to be reachable on clearnet and onion at the same time by default, configured from one place per role, so that clearnet users and Tor users reach the same deployment and every page stays inside the network it was requested on.

Implementing pull request: [PR 414](https://github.com/infinito-nexus/core/pull/414).

## Decisions

Operator-confirmed. These MUST NOT be re-litigated during implementation.

| # | Decision |
|---|---|
| 1 | A node runs in one of three network modes: `clearnet` 🌐 (clearnet only), `tor` 🧅 (onion only), `multi` 🌈 (clearnet and onion). |
| 2 | The node mode defaults to `multi` when `svc-net-tor` is deployed and to `clearnet` otherwise. `tor` is selectable per node. |
| 3 | `roles/<role>/meta/networks.yml` is the single point of truth for a role's networks. `reachability.modes` lists the networks the role may be served on (`clearnet`, `tor`). An empty list or no key means every network, which is `multi` on a node that runs Tor. `multi` is not a list value. |
| 4 | `reachability.single_mode: true` marks a role that can only be reachable under one domain. It is served on `tor` when the node runs Tor and on `clearnet` otherwise. A role whose allowed networks exclude the node's only network MUST fail the deploy with an explicit error. |
| 5 | Clearnet is canonical whenever it is active: `url.base`, cross-app references, OIDC endpoints, e-mail identities and the CI base URL use the clearnet domain. |
| 6 | SSO publishes exactly one issuer. In `multi` mode it is the clearnet https URL, and onion users of a `multi` app authenticate at that clearnet IdP. |
| 7 | Clearnet vhosts of `multi` apps send an `Onion-Location` header that points at their onion sibling. |
| 8 | `meta/services.yml` keeps only the Tor service bond (`bond`, `enabled`, `shared`). `exclusive` and `primary` are removed repository-wide. |
| 9 | The CI network axis rotates `clearnet`, `tor` and `multi`. A `multi` row runs the full Playwright suite once, on the clearnet or the onion URL picked at random, together with the guest persona and the cross-network leak spec. |
| 10 | Networks live in one registry, so Handshake and later networks plug in without a redesign. Only clearnet and onion are implemented. |
| 11 | The generic mechanism replaces every Wazuh-specific dual-stack workaround of PR 414. |

## Model

- **Network registry.** One entry per network with its provider role, sibling-domain derivation, transport (TLS policy, scheme, port), client reachability (browser proxy) and CSP scheme.
  `clearnet` is implicit and has no provider.
  `onion` is provided by `svc-net-tor`, derives `<sub>.<node>.onion` from `<sub>.<DOMAIN_PRIMARY>`, serves plain HTTP on port 80 and needs the Tor SOCKS proxy in browsers.
  `handshake` is reserved and not implemented.
- **Mode presets.** `clearnet` = {clearnet}, `tor` = {onion}, `multi` = {clearnet, onion}.
- **Effective networks of a role.** The node preset intersected with the role's `reachability.modes`, then reduced to one network when `single_mode` is set: `tor` if the node runs Tor, `clearnet` otherwise. An empty result fails the deploy.
- **Roles without a Tor bond.** A role that declares no `tor` service (a server-side backend such as `web-app-seaweedfs`) keeps its declared clearnet domains on every node and is never a mismatch.
- **Network siblings.** Every logical domain of a role expands to one domain per effective network. The clearnet sibling is canonical when present.
- **Per-vhost decisions.** One vhost per sibling. TLS, injected snippets, CSP, redirects and health probes are decided by the vhost domain, and every cross-app URL rendered into a vhost comes from that vhost's network.

## Target Configuration

```yaml
# roles/<role>/meta/networks.yml
local:
  subnet: 192.168.81.0/24
reachability:
  modes: [clearnet, tor]
  single_mode: false
```

Both keys are optional. `modes: []` or no `modes` key means every network, and no `single_mode` key means `false`.

```yaml
# inventory (node)
NETWORK_MODE: multi
```

`reachability` is used instead of a top-level `modes` key because `overlay.modes` in the same file already lists deploy modes (`compose`, `swarm`).

## Codebase Facts

Verified on the PR 414 worktree; build on these.

| Fact | Where |
|---|---|
| Onion siblings are injected per app from `services.tor.exclusive` and `services.tor.primary`, consumer value first, provider default second | [domains.py](../../utils/cache/domains.py) `_inject_onion_domains`, [config.py](../../utils/roles/applications/services/config.py) `resolve_service_config` |
| The provider default is `exclusive: true`, `primary: true`; the only consumer override is Matrix `exclusive: true` | [services.yml](../../roles/svc-net-tor/meta/services.yml), [services.yml](../../roles/web-app-matrix/meta/services.yml) |
| `lookup('tls', <domain>)` already returns per-domain protocol for any domain in the merged map; app-id terms are aligned to the consumer app only in the onion to clearnet direction | [tls.py](../../plugins/lookup/tls.py), [tls_common.py](../../utils/tls_common.py) `resolve_term`, `align_domain_to_consumer` |
| Only the primary domain gets a vhost by default, and the TLS layer is switched on per app | [main.yml](../../roles/sys-stk-front-proxy/tasks/main.yml), [main.yml](../../roles/sys-stk-full/tasks/main.yml) |
| Roles registering explicit domains: bluesky, matrix, minio, seaweedfs; loops over all domains: mastodon, peertube, wordpress, joomla | the roles' `tasks/` |
| Injected snippets live in one Lua file per app and CSP script hashes are stored per app, so two vhosts of one app share snippets | [main.yml](../../roles/sys-front-inj-all/tasks/main.yml), [location.lua.j2](../../roles/sys-front-inj-all/templates/location.lua.j2) |
| The only runtime network rewrite is CDN clearnet to onion for onion hosts | [body_filter.lua.j2](../../roles/sys-front-inj-all/templates/body_filter.lua.j2) |
| The CSP header is built per app without the vhost domain | [content_security_policy.conf.j2](../../roles/sys-svc-proxy/templates/headers/content_security_policy.conf.j2), [csp_filters.py](../../plugins/filter/csp_filters.py) |
| Keycloak redirect URIs already cover every domain of every SSO consumer with a per-domain scheme | [redirect_uris.py](../../plugins/lookup/redirect_uris.py) |
| Keycloak pins its issuer to `KC_HOSTNAME={{ OIDC.URL }}`; on a Tor node that is `http://auth.<onion>` | [env.j2](../../roles/web-app-keycloak/templates/env.j2), [11_oidc.yml](../../group_vars/all/11_oidc.yml) |
| The web health check uses one global protocol from `DOMAIN_PRIMARY`; the CSP crawler scans either `servers/http` or `servers/https` | [00_core.yml](../../roles/sys-ctl-hlth-webserver/tasks/00_core.yml), [00_core.yml](../../roles/sys-ctl-hlth-csp/tasks/00_core.yml) |
| Redirect vhosts use the source domain's scheme, and the node-onion apex redirects to the canonical homepage | [redirect-domain.conf.j2](../../roles/web-opt-rdr-domains/templates/redirect-domain.conf.j2), [current_play_redirect_domains.py](../../plugins/lookup/current_play_redirect_domains.py) |
| The CI network axis knows two states from `INFINITO_TOR` (`auto`, `enforced`, `exclusive`, `disabled`); the only deploy difference is `disable=tor` | `tor.py`, now [network.py](../../utils/github/variant/network.py), [axes.py](../../utils/github/variant/axes.py), [services_disabler.py](../../cli/administration/inventory/provision/services_disabler.py) |
| Playwright runs one pass per role against `lookup('tls', application_id, 'url.base')` and reaches onion through the Tor SOCKS proxy | [02_run_one.yml](../../roles/test-e2e-playwright/tasks/02_run_one.yml), [main.yml](../../roles/test-e2e-playwright/vars/main.yml) |
| The svc-net-tor README claims `X-Forwarded-Proto: https`, but the location template sends `$scheme` | [README.md](../../roles/svc-net-tor/README.md), [html.conf.j2](../../roles/sys-svc-proxy/templates/location/html.conf.j2) |
| Fork run 35925283225 of the dual-stack Wazuh head served both vhosts, but its clearnet page loaded `http://cdn.<onion>` and `http://matomo.<onion>` assets that the browser blocked as mixed content | job 107412507989 log |

## Acceptance Criteria

### Configuration and model

- [ ] `meta/networks.yml` accepts `reachability.modes` with values from `clearnet` and `tor`, treats an empty list or a missing key as every network, and a lint rejects any other value including `multi`.
- [ ] `meta/networks.yml` accepts `reachability.single_mode` as a boolean, and a role with `single_mode: true` is served on `tor` when the node runs Tor and on `clearnet` otherwise.
- [ ] `NETWORK_MODE` accepts `clearnet`, `tor` and `multi`, defaults to `multi` when `svc-net-tor` is deployed and to `clearnet` otherwise.
- [ ] The effective networks of a role follow Decisions 3 and 4, covered by unit tests for every combination of node mode, `modes` and `single_mode` including the explicit failure.
- [ ] No `meta/services.yml` contains `exclusive` or `primary` under `tor`, and a lint rejects them.
- [ ] Network properties (sibling derivation, TLS policy, scheme, browser proxy) are read from the registry, and no `.onion` suffix check remains outside it in plugins, utils, filters and role scripts.
- [ ] The registry reserves `handshake` without implementing it, and the design page documents the steps to add a network.

### Domains and vhosts

- [ ] In `multi` mode every canonical domain of a role has exactly one onion sibling in `lookup('domains')`, clearnet first.
- [ ] `sys-stk-front-proxy` renders one vhost per network sibling of the domain it receives, and no vhost is rendered twice.
- [ ] Roles that register explicit domains (bluesky, matrix, minio, seaweedfs, mastodon, peertube, wordpress, joomla) serve every network sibling without network-specific code in the role.
- [ ] TLS is decided by the vhost domain in `sys-stk-front-proxy`, `sys-front-tls` and `nginx_ssl_header.j2` without a `default()` fallback: onion vhosts listen on port 80 in plain HTTP, clearnet vhosts follow `TLS_MODE`.
- [ ] Clearnet vhosts of `multi` apps send `Onion-Location: http://<onion sibling>$request_uri`, and no other vhost sends it.
- [ ] The shared location template forwards `X-Forwarded-Host`, and the svc-net-tor README describes the `X-Forwarded-Proto` value that is actually sent.

### Per-vhost network alignment

- [ ] Every cross-app URL rendered for a vhost (CDN, CSS, Matomo, logout, dashboard iframe origin, simpleicons, mirror) uses the provider domain of that vhost's network, in both directions.
- [ ] Injected snippets and their CSP hashes are rendered per vhost, so the clearnet and the onion vhost of one app serve their own correct snippets.
- [ ] The CDN-only runtime rewrite in `body_filter.lua.j2` is removed.
- [ ] The CSP header is built per vhost domain and lists only sources of that vhost's network plus the single SSO issuer.
- [ ] Redirect vhosts (aliases, `www`, node-onion apex) redirect inside the source's network, so source and target share one scheme.

### SSO

- [ ] In `multi` mode Keycloak serves both vhosts and publishes the single issuer `https://auth.<clearnet>/realms/<realm>` for requests on either vhost.
- [ ] In `tor` mode Keycloak keeps its onion issuer, and in `clearnet` mode its clearnet issuer.
- [ ] A `multi` SSO app completes an OIDC login on its clearnet vhost (Playwright).
- [ ] Keycloak redirect URIs and web origins include both siblings of every SSO consumer, each with its own scheme.

### Checks

- [ ] `sys-ctl-hlth-webserver` probes every vhost of every effective network with that vhost's scheme, and no global protocol flag remains.
- [ ] `sys-ctl-hlth-csp` crawls the http and the https vhosts in one run.

### CI

- [ ] The CI network axis offers `clearnet` 🌐, `tor` 🧅 and `multi` 🌈 (glyphs in `utils/symbol_glossary.py`), selected by one input that replaces `INFINITO_TOR`.
- [ ] A matrix row only takes node modes its role can be served in, and a `single_mode` role never takes a `multi` row.
- [ ] On `multi` rows Playwright runs the full role suite once, on the clearnet or the onion URL picked at random, and keeps that pick for the flake retry.
- [ ] On `multi` rows the run includes the guest persona and a shared cross-network leak spec.
- [ ] The leak spec fails when a page requests a host of another network or loads blocked mixed content, proven by a negative control that reproduces the Wazuh mixed-content regression of fork run 35925283225.
- [ ] `tor` rows keep running the full role suite on the onion URL.

### Roles

- [ ] Every role with a Tor bond either passes a `multi` row or sets `reachability.single_mode: true` or restricts `reachability.modes`, each with a written reason that a lint enforces.
- [ ] web-app-matrix expresses its former `exclusive: true` as `reachability.single_mode: true`.
- [ ] web-app-wazuh contains no network-specific code (no onion variable, no second front-proxy include, no forked vhost template) and passes a `multi` row including the onion leak pass.
- [ ] The "dual-family providers" item in `TODO.md` is removed.

### Quality

- [ ] Unit tests cover the registry, sibling derivation, mode resolution, bidirectional alignment and per-vhost TLS.
- [ ] A design page under `docs/contributing/design/` documents the network modes, `meta/networks.yml` and the registry.
- [ ] `make quality-high` is green.

## Out of Scope

- HTTPS on onion vhosts, blocked on a CA that issues for v3 `.onion` (see `TODO.md`).
- Per-network OIDC issuers and mirrored SSO realms.
- Implementing Handshake or any network beyond clearnet and onion.
- Migrating identities of existing nodes between networks.

## Implementation Order

1. Registry, `NETWORK_MODE`, the `reachability.modes` and `reachability.single_mode` schema, network resolution and their lints and unit tests.
2. Sibling injection from the effective mode, removal of `exclusive` and `primary`, Matrix migration.
3. Vhost fan-out in `sys-stk-front-proxy` and per-vhost TLS.
4. Per-vhost alignment: injected snippets, CSP, redirects, `Onion-Location`, forwarded headers.
5. Keycloak single clearnet issuer in `multi` mode.
6. Health probe and CSP crawler per vhost.
7. CI network axis, the second Playwright pass and the leak spec with its negative control.
8. Wazuh cleanup, then `multi` rows for every role with a Tor bond and justified restrictions where a role fails.
9. Design page, `TODO.md` cleanup, `make quality-high`.

## Validation

```bash
make compose-deploy mode=reinstall apps=web-app-wazuh variant=0 full_cycle=false
make compose-playwright role=web-app-wazuh
curl -sI https://wazuh.infinito.test/ | grep -i '^onion-location'
```

## Commit Policy

- The agent MUST NOT push. When the criteria are green, the operator runs `git-sign-push` outside the sandbox.
