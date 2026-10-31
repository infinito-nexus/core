# Network Modes 🌈

How a node decides which networks it serves each role on, and how vhosts, TLS, cross-app URLs, checks and CI follow that decision.
For general documentation rules such as links, writing style, RFC 2119 keywords, and Sphinx behavior, see [documentation.md](../documentation.md).
For the Tor provider itself see [svc-net-tor](../../../roles/svc-net-tor/README.md).

## Registry 🗂️

[reachability.py](../../../utils/networks/reachability.py) holds one `Network` entry per network. Every other module asks it (`network_of`, `sibling_domain`, `network(name)`) instead of testing a domain suffix of its own.

| Network | Label | Provider | Suffix | TLS | Browser proxy |
|---|---|---|---|---|---|
| `clearnet` | `clearnet` | none | none | yes | no |
| `tor` | `onion` | `svc-net-tor` | `.onion` | no | yes |

`handshake` is listed in `RESERVED_NETWORKS`; `network('handshake')` raises until it is implemented.

## Node Modes 🧭

A node runs in one `NETWORK_MODE`:

| Mode | Networks served |
|---|---|
| `clearnet` 🌐 | clearnet |
| `tor` 🧅 | tor |
| `multi` 🌈 | clearnet and tor |

`NETWORK_MODE` defaults to empty in [08_networks.yml](../../../group_vars/all/08_networks.yml). Empty resolves to `multi` when `svc-net-tor` is deployed with a node onion address and to `clearnet` otherwise. `tor` or `multi` on a node without the provider fails the deploy.

## Role Reachability 🎚️

`roles/<role>/meta/networks.yml` is the single point of truth for the networks one role may be served on:

```yaml
reachability:
  modes: [clearnet, tor]
  single_mode: true # nocheck: network-reachability  <why the role answers under one domain only>
  handover: true # nocheck: network-reachability  <why the role answers under its canonical URL only>
```

- `modes` lists networks from the registry. An empty list or no key means every network. `multi` is a node mode, not a list value.
- `single_mode: true` serves the role on `tor` when the node runs Tor and on `clearnet` otherwise, never on both.
- `handover: true` keeps every network sibling, but each sibling outside the canonical network answers `302` to the same path on the canonical URL and advertises no `Onion-Location`. The webserver health check expects that `302`, the CSP crawl skips those siblings and Playwright tests only the canonical domain.
- `single_mode: true`, `handover: true` and a `modes` list below every network each carry `# nocheck: network-reachability` plus a reason on or directly above their line ([suppression.md](../actions/testing/suppression.md)).

[test_network_reachability.py](../../../tests/lint/ansible/roles/meta/test_network_reachability.py) enforces the schema and the marker. `meta/services.yml` keeps only the Tor service bond (`bond`, `enabled`, `shared`).

The effective networks of a role are the node's networks that the role allows, where `tor` also needs the role's `services.tor.enabled` to render true, reduced to one network by `single_mode`. A deployed role with no effective network fails the deploy. A role without a `tor` service keeps its clearnet domains on every node.

## Domains and Vhosts 🌍

1. `get_merged_domains` in [domains.py](../../../utils/cache/domains.py) expands every canonical domain of a role into one sibling per effective network, canonical network first. Lists gain the sibling after the clearnet entry; named dicts gain a `<key>_onion` entry.
2. `lookup('network_siblings', domain)` returns the vhosts one domain is served under. [sys-stk-front-proxy](../../../roles/sys-stk-front-proxy/tasks/vhost.yml) renders one vhost per sibling, and a non-canonical sibling handed in directly renders nothing, so no vhost is rendered twice.
3. TLS is decided per vhost with `lookup('tls', domain, ...)`: onion vhosts listen on port 80 in plain HTTP, clearnet vhosts follow `TLS_MODE`.
4. Every app-id term of the `tls` lookup is aligned to the network of the vhost being rendered (`align_domain_to_consumer` in [tls_common.py](../../../utils/tls_common.py)), in both directions. The SSO provider is never aligned: the node publishes one issuer, the canonical one.
5. Injected snippets ([sys-front-inj-all](../../../roles/sys-front-inj-all/)) and the CSP header ([content_security_policy.conf.j2](../../../roles/sys-svc-proxy/templates/headers/content_security_policy.conf.j2)) are rendered per vhost. Clearnet vhosts of a role served on more than one network send `Onion-Location`.
6. Redirect vhosts redirect inside the network of their source domain.

## Network-Aligned Values 🧭

A value that names an own or peer host MUST point to the network of the vhost that serves it. Pick the form by how the value is consumed:

| Value | Form | How |
|---|---|---|
| Allowlist a peer checks (OIDC redirect and post-logout URIs, web origins, Collabora `aliasgroupN`, trusted domains, CSP sources) | Union of every sibling, rendered once | `lookup('network_urls', url)` for a URL, a loop over `lookup('network_siblings', domain)` when each entry needs its own scheme or port |
| Asset a browser loads (logo, icon, manifest icon, CDN file) | Same-origin path | `lookup('design', ...).relative_urls`, `lookup('cdn', ...).relative_urls`; `/_infinito/cdn/` is served on every vhost |
| Object-store file a browser loads (uploads, media in a public bucket) | Same-origin path | `lookup('objstore', application_id, 'relative_url')`, which is `/_infinito/objstore/<bucket>` for a shared consumer with `public: true`; [locations.conf.j2](../../../roles/web-svc-seaweedfs/templates/nginx/locations.conf.j2) serves it on every vhost of that consumer with `GET` and `HEAD` only, no query string and no path ending in `/` |
| Pointer a browser follows from a snippet rendered per vhost (injected script, proxy config) | Rendered per vhost | `lookup('tls', '<app-id>', 'url.base')` with `domain` in scope, which aligns the term to the vhost's network |
| Own public URL an application keeps in one server-side setting | Request-derived or one instance per network | Let the application read `X-Forwarded-Host` and `X-Forwarded-Proto`, which every vhost sends; otherwise run one instance per network as [web-svc-logout](../../../roles/web-svc-logout/templates/compose.yml.j2) does with `network_instances` |

- A role MUST NOT write an onion host by hand or rewrite hosts in its own proxy config.
- The SSO issuer is the one host that stays canonical on every network.
- Every plain-HTTP vhost strips `Secure` from upstream cookies with `proxy_cookie_flags ~ nosecure` ([nginx_ssl_header.j2](../../../roles/sys-front-tls/templates/nginx_ssl_header.j2)). A location that sets its own `proxy_cookie_flags` replaces this rule for that location.
- Logout: Keycloak holds one front-channel URL per client, the canonical logout conductor. On a vhost outside the canonical network the injected logout patch adds `client_id` and `post_logout_redirect_uri` set to that network's conductor, and Keycloak registers every conductor sibling as post-logout redirect URI next to `+`. An external issuer (`OIDC_OVERRIDE.URL`) keeps the bare logout URL.
- [test_network_allowlist_sinks.py](../../../tests/lint/ansible/roles/test_network_allowlist_sinks.py) fails when a role template names an allowlist sink without the sibling union. Suppress a single-network peer with `# nocheck: network-allowlist` and a reason.

## Checks 🩺

- [sys-ctl-hlth-webserver](../../../roles/sys-ctl-hlth-webserver/) probes every vhost with that vhost's scheme.
- [sys-ctl-hlth-csp](../../../roles/sys-ctl-hlth-csp/) crawls the `http` and the `https` vhosts in one run; hosts under the Tor suffix go through the Tor SOCKS proxy.

## CI 🚀

- [network.py](../../../utils/github/variant/network.py) derives the node modes a matrix row can take from the role's Tor bond, `reachability` and whether its deploy pulls the Tor provider in; the `network` input (`auto`, `clearnet`, `tor`, `multi`) narrows them. See [README.md](../../../.github/workflows/README.md).
- A row hands its mode to the deploy as the `network` variable, which provisioning writes into the inventory as `NETWORK_MODE` ([network_mode.py](../../../cli/administration/inventory/provision/network_mode.py)). `make compose-deploy apps=<role> network=tor` does the same locally.
- [test-e2e-playwright](../../../roles/test-e2e-playwright/) runs the role's suite once, on the vhost of one network sibling. On a node serving the role on several networks the sibling is picked at random and kept for the flake retry, and [network-leak.spec.js](../../../roles/test-e2e-playwright/files/network-leak.spec.js) joins the run with the guest persona. The leak spec fails when a document requests a host of another network or the browser blocks mixed content; the SSO issuer is the one host every network may reach.

## Adding a Network ➕

1. Add a `Network` entry to `NETWORKS` in [reachability.py](../../../utils/networks/reachability.py) with its provider role, suffix, TLS policy, browser-proxy flag and probe timeout, and remove its name from `RESERVED_NETWORKS`.
2. Add the node modes that serve it to `NODE_MODES`.
3. Extend `sibling_domain` with the way the network derives a host from a clearnet one.
4. Gate the network on its provider's service bond in `allowed_networks`, as `tor` is gated on `services.tor.enabled`.
5. Add a glyph for each new node mode to [symbol_glossary.py](../../../utils/symbol_glossary.py).
