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
```

- `modes` lists networks from the registry. An empty list or no key means every network. `multi` is a node mode, not a list value.
- `single_mode: true` serves the role on `tor` when the node runs Tor and on `clearnet` otherwise, never on both.
- `single_mode: true` and a `modes` list below every network each carry `# nocheck: network-reachability` plus a reason on or directly above their line ([suppression.md](../actions/testing/suppression.md)).

[test_network_reachability.py](../../../tests/lint/ansible/roles/meta/test_network_reachability.py) enforces the schema and the marker. `meta/services.yml` keeps only the Tor service bond (`bond`, `enabled`, `shared`).

The effective networks of a role are the node's networks that the role allows, where `tor` also needs the role's `services.tor.enabled` to render true, reduced to one network by `single_mode`. A deployed role with no effective network fails the deploy. A role without a `tor` service keeps its clearnet domains on every node.

## Domains and Vhosts 🌍

1. `get_merged_domains` in [domains.py](../../../utils/cache/domains.py) expands every canonical domain of a role into one sibling per effective network, canonical network first. Lists gain the sibling after the clearnet entry; named dicts gain a `<key>_onion` entry.
2. `lookup('network_siblings', domain)` returns the vhosts one domain is served under. [sys-stk-front-proxy](../../../roles/sys-stk-front-proxy/tasks/vhost.yml) renders one vhost per sibling, and a non-canonical sibling handed in directly renders nothing, so no vhost is rendered twice.
3. TLS is decided per vhost with `lookup('tls', domain, ...)`: onion vhosts listen on port 80 in plain HTTP, clearnet vhosts follow `TLS_MODE`.
4. Every app-id term of the `tls` lookup is aligned to the network of the vhost being rendered (`align_domain_to_consumer` in [tls_common.py](../../../utils/tls_common.py)), in both directions. The SSO provider is never aligned: the node publishes one issuer, the canonical one.
5. Injected snippets ([sys-front-inj-all](../../../roles/sys-front-inj-all/)) and the CSP header ([content_security_policy.conf.j2](../../../roles/sys-svc-proxy/templates/headers/content_security_policy.conf.j2)) are rendered per vhost. Clearnet vhosts of a role served on more than one network send `Onion-Location`.
6. Redirect vhosts redirect inside the network of their source domain.

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
