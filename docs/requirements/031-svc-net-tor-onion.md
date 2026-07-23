# 031 - svc-net-tor: Full Tor Onion Node

## User Story

As a self-hoster running Infinito.Nexus behind NAT/CGNAT/dynamic IP (Raspberry Pi, edge node, home server), I want a `svc-net-tor` role that makes the node's primary domain a Tor v3 `.onion` address so that the entire stack (web, SSO, LDAP, CA) is reachable over Tor without public IP, port forwarding, VPS, or DynDNS — while individual apps can still attach extra public domains with their own TLS.

## Model

**`DOMAIN_PRIMARY` = the node's `.onion` address.** Everything derives from `DOMAIN_PRIMARY`, so the whole node becomes Tor-native with **zero domain-transform code**:

- Vhosts: `next.cloud.{{ DOMAIN_PRIMARY }}` → `next.cloud.<NODE_ONION>.onion`
- OIDC issuer, redirect URIs, web-origins: onion — one realm, one issuer, consistent
- `LDAP_DN_BASE`, user/admin emails, oauth2-proxy `email_domains`, CA identity: all onion, mutually consistent (users `@<NODE_ONION>.onion` pass the oauth2-proxy email filter)

The `.onion` is a **deploy-time input**: a CLI helper mints the v3 key offline during inventory build, vaults it, and sets `DOMAIN_PRIMARY`. It must NOT be a runtime fact — `DOMAIN_PRIMARY` is consumed at build time (LDAP base, CA, applications cache). The role restores the minted key into the hidden-service volume before Tor starts.

**All-or-nothing:** a partial shift (web onion, identity clearnet) breaks oauth2-proxy email matching ([oauth2-proxy-keycloak.cfg.j2:32](../../roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2) sets `email_domains = "{{ DOMAIN_PRIMARY }}"`). Fresh onion nodes only; migrating an existing clearnet node is out of scope (base DN + all identities would shift).

## Codebase facts (verified; build on these)

| Fact | Where |
|---|---|
| OpenResty runs `network_mode: host`, binds 80/443, `proxy_pass http://127.0.0.1:<port>` | [`roles/svc-prx-openresty/templates/compose.yml.j2`](../../roles/svc-prx-openresty/templates/compose.yml.j2), [`roles/sys-svc-proxy/templates/location/html.conf.j2`](../../roles/sys-svc-proxy/templates/location/html.conf.j2) |
| TLS-disabled vhosts serve plain HTTP on `:80`; the http→https 301 exists only in the TLS layer | [`roles/sys-front-tls/templates/http.conf.j2`](../../roles/sys-front-tls/templates/http.conf.j2) |
| TLS is resolved per `(domain\|application_id)` with `TLS_MODE`/`TLS_ENABLED` defaults, flavors in `AVAILABLE_FLAVORS` | [`plugins/lookup/tls.py`](../../plugins/lookup/tls.py), `utils/tls_common` |
| `DOMAIN_PRIMARY` defined once; `LDAP_DN_BASE`, CA identity, contact email derive from it | [`group_vars/all/00_general.yml:50`](../../group_vars/all/00_general.yml), [`group_vars/all/12_ldap.yml`](../../group_vars/all/12_ldap.yml), [`group_vars/all/02_tls.yml`](../../group_vars/all/02_tls.yml), [`group_vars/all/14_about.yml`](../../group_vars/all/14_about.yml) |
| Keycloak redirect URIs/web-origins are computed from `lookup('domains')` at deploy | [`roles/web-app-keycloak/filter_plugins/redirect_uris.py`](../../roles/web-app-keycloak/filter_plugins/redirect_uris.py), [`roles/web-app-keycloak/vars/main.yml`](../../roles/web-app-keycloak/vars/main.yml) |
| Apps register one vhost per domain via `include_role: sys-stk-front-proxy` with `domain` + `http_port`; multi-domain is established practice | [`roles/sys-stk-front-proxy/tasks/main.yml`](../../roles/sys-stk-front-proxy/tasks/main.yml), [`roles/web-app-matrix/tasks/flavor/compose/03_webserver.yml`](../../roles/web-app-matrix/) |
| Extra app domains live in `applications.<app>.server.domains.{canonical,aliases}` (str/list/dict) | [`utils/domains/application_domain_index.py`](../../utils/domains/application_domain_index.py), [`plugins/filter/canonical_domains_map.py`](../../plugins/filter/canonical_domains_map.py) |
| Inventory build/secrets tooling (mint-helper integration point) | [`cli/administration/inventory/credentials/`](../../cli/administration/inventory/) |
| Container-service role archetype (compose sidecar, `meta/services.yml` entity, `run_once_` guard) | [`roles/svc-ai-ollama/`](../../roles/svc-ai-ollama/) |
| Role file/entry policy enforced by lint (mandatory files, galaxy_info canon, README sections + exact Credits block, lifecycle values, service bond) | `utils/roles/mapping.py`, `tests/lint/ansible/roles/`, `tests/integration/roles/meta/test_mapping.py` |
| No prior server-side Tor art in the repo (`desk-torbrowser` is desktop client only) | repo-wide grep |

## Tor facts (verified upstream)

- **Subdomains:** `sub.<addr>.onion` routes to the **same** hidden service; the client sends the full `Host:` header → vhost routing works exactly like clearnet. ([address-spec](https://spec.torproject.org/address-spec), [RFC 7686 §2](https://www.rfc-editor.org/rfc/rfc7686.html))
- **v3 address algorithm** (needed for offline mint): `address = base32(PUBKEY ‖ CHECKSUM ‖ VERSION) + ".onion"`, `CHECKSUM = SHA3-256(".onion checksum" ‖ PUBKEY ‖ VERSION)[:2]`, `VERSION = 0x03`, PUBKEY = 32-byte ed25519 master pubkey.
- **Key-file formats** in `HiddenServiceDir`: `hostname` (address + `\n`), `hs_ed25519_public_key` (`== ed25519v1-public: type0 ==` header + 32-byte key), `hs_ed25519_secret_key` (`== ed25519v1-secret: type0 ==` header + **64-byte expanded** secret key = SHA-512(seed) clamped).
- **`http://*.onion` is a Secure Context** → `Secure` cookies + secure-context APIs work over plain-HTTP onion; hence forward `X-Forwarded-Proto: https`. ([W3C Secure Contexts](https://www.w3.org/TR/secure-contexts/))
- **`.onion` is in the Public Suffix List** → `user@x.onion` passes most validators.
- **No Let's Encrypt for `.onion`** (ACME needs public DNS). Onion transport is already encrypted + server-authenticated (address = pubkey).

## Decisions (operator-confirmed; do not re-litigate)

| # | Decision |
|---|---|
| 1 | Role `svc-net-tor`, container-service archetype ([`svc-ai-ollama`](../../roles/svc-ai-ollama/) pattern), `application_id: svc-net-tor`. Category `svc-net-*` per [`roles/categories.yml`](../../roles/categories.yml). |
| 2 | **Full onion node**: `DOMAIN_PRIMARY` = node `.onion`; entire stack shifts together. No web/identity split, no domain-transform lookup. |
| 3 | **One node key + per-app subdomains** (`<sub>.<NODE_ONION>.onion`), Host-header-routed. No per-app onions in MVP. |
| 4 | **Tor = compose sidecar**, `network_mode: host`, keys on a named volume, restored from the vaulted mint **before** Tor starts. Backup via `svc-bkp-container-2-local`. |
| 5 | **HTTP on the onion side** (TLS forced off for `.onion`), vhosts on `:80`, upstream gets `X-Forwarded-Proto: https`. |
| 6 | **Offline Python mint** at inventory build: ed25519 → address → exact Tor key-file formats → vault → `DOMAIN_PRIMARY`. Idempotent (existing key is reused, never regenerated). No Docker/Tor needed at build time. |
| 7 | SSO needs no special handling: Keycloak domain is onion ⇒ one onion issuer/realm; onion emails match `email_domains`. |
| 8 | **Tor image built via `files/Dockerfile`** from a pinned Debian `tor` package (`deb.debian.org`; no sandbox-allowlist change). `deb.torproject.org` = documented alternative requiring an allowlist entry. |
| 9 | **Per-domain TLS via app-level override**: extra public domains under `applications.<app>.server.domains` deploy as additional HTTPS vhosts; flavor from `applications.<app>.tls.mode` (default `TLS_MODE`). `.onion` → always HTTP. No per-domain TLS map. |
| 10 | **`TOR_EGRESS_ENABLED: false` default.** Flag + plumbing in MVP (SOCKS `127.0.0.1:9050` reachable for containers when enabled, documented); transparent egress torification out of scope. Inbound is always onion. |
| 11 | **CI runs a real Tor E2E** (`torsocks curl` against the minted onion) with retry logic; unit tests remain the merge-blocking base. |

## Target Schema

### Role layout

```
roles/svc-net-tor/
├── README.md                       # lint-conform (sections, exact Credits block, no heading emojis)
├── files/Dockerfile                # Debian base + pinned `tor`
├── meta/
│   ├── main.yml                    # canonical galaxy_info (author/license/company/platforms exact canon)
│   ├── services.yml                # `tor` entity (below)
│   └── volumes.yml                 # tor_data -> HiddenServiceDir
├── tasks/
│   ├── main.yml                    # run_once_svc_net_tor guard
│   ├── 01_restore_key.yml          # vaulted hostname + hs_ed25519_* -> volume, strict perms, never overwrite
│   └── 02_core.yml                 # network routine + compose up + render torrc (handler-driven reload)
├── templates/
│   ├── compose.yml.j2              # sidecar: network_mode host, tor_data volume, base/container includes
│   └── torrc.j2
└── vars/main.yml                   # application_id + lookup('config', ...) resolved vars
```

No onion vhost template, no domain lookup changes: onion domains fall out of `DOMAIN_PRIMARY`; the standard vhost serves them on `:80` because TLS resolves disabled.

### `meta/services.yml`

```yaml
tor:
  bond: 1
  enabled: "{{ 'svc-net-tor' in group_names }}"
  shared:  "{{ 'svc-net-tor' in group_names }}"
  build: true
  image: svc-net-tor
  version: "<pinned tor x.y.z>"
  name: tor
  backup:
    no_stop_required: false     # stop for consistent key-volume copy
  lifecycle: alpha
  # no public ports; SocksPort/ControlPort bind 127.0.0.1 only
```

### `torrc.j2`

```
SocksPort 127.0.0.1:9050
ControlPort 127.0.0.1:9051
DataDirectory /var/lib/tor
HiddenServiceDir /var/lib/tor/infinito/node/
HiddenServiceVersion 3
HiddenServicePort 80 127.0.0.1:80
```

One `HiddenServicePort` covers all apps: every `<sub>.<NODE_ONION>.onion` request arrives on `127.0.0.1:80` where OpenResty routes by `Host`.

### CLI mint helper

Location: under [`cli/administration/inventory/`](../../cli/administration/inventory/), integrated with `credentials/{emit,vault}.py`; runs automatically during inventory build when `svc-net-tor` is in the target groups.

1. If a vaulted key exists → reuse (idempotent, address stability is the contract).
2. Else: generate ed25519 seed → compute expanded secret key (SHA-512(seed), clamp) → derive address per the algorithm above → write the three Tor key files byte-exact.
3. Vault `hostname` + both key files; emit `DOMAIN_PRIMARY: <address>.onion` into the generated inventory.
4. Unit tests: known seed → known address test vector; idempotent reuse; file-format byte-exactness (headers + lengths).

`tasks/01_restore_key.yml` writes the vaulted files into the volume-backed `HiddenServiceDir` (owner = in-container tor UID, `0700` dir, `0600` secret) before the Tor container starts. Existing on-disk keys are never overwritten.

### Per-domain TLS (extend `tls.py` / `utils/tls_common`)

- Domain ends `.onion` → `enabled=false`, `protocols.web=http`, `ports.web=80`, no ACME. Overrides `TLS_MODE` unconditionally.
- Non-onion domain → flavor from `applications.<app>.tls.mode`, else `TLS_MODE`.
- Foreign domains under `applications.<app>.server.domains` register as separate HTTPS vhosts (existing per-domain `sys-stk-front-proxy` calls), same upstream as the onion vhost.

### Config

```yaml
DOMAIN_PRIMARY: "<node>.onion"     # written by the mint helper
TOR_EGRESS_ENABLED: false          # Decision #10

applications:
  <app-id>:
    server:
      domains:
        canonical: [ "app.example.org" ]   # optional extra public domain
    tls:
      mode: letsencrypt                    # flavor for that app's non-onion domains
```

## Acceptance Criteria

### Scaffolding & lint

- [ ] `roles/svc-net-tor/` matches the layout; `application_id: svc-net-tor`; `run_once_svc_net_tor` guard; all meta lint green (mapping, galaxy canon, layout, bond, README).
- [ ] `files/Dockerfile` pins `tor` (no `:latest`); image builds in the stack.

### Mint helper & key persistence

- [ ] Helper mints offline, vaults `hostname` + `hs_ed25519_{public,secret}_key`, emits `DOMAIN_PRIMARY`; re-running reuses the key (address unchanged).
- [ ] Unit tests: known-vector address determinism, idempotent reuse, byte-exact file formats.
- [ ] `01_restore_key.yml` restores keys with strict perms before Tor starts; never overwrites existing keys; Tor serves exactly the minted address.
- [ ] Address survives redeploy, update, full-cycle reinstall; restoring the vault on a fresh box reproduces the same address; key volume covered by `svc-bkp-container-2-local`.

### Serving

- [ ] Tor sidecar bootstraps (`network_mode: host`); 9050/9051 bind `127.0.0.1` only; zero published ports.
- [ ] `lookup('tls', '<x>.onion')` → http/disabled/80, no ACME attempted; app vhosts serve onion `server_name`s on `:80`; every app reachable at `<sub>.<NODE_ONION>.onion` through `HiddenServicePort 80 → 127.0.0.1:80`.
- [ ] Onion requests reach upstreams with `X-Forwarded-Proto: https`; no `.onion` request is 301'd to https; alias/www canonicalization stays onion-internal; CSP origins (CDN, Matomo, Keycloak, logout) resolve onion — no clearnet leak.

### SSO / identity consistency

- [ ] OIDC login completes end-to-end over `.onion`: issuer, redirect URIs, web-origins all onion; no redirect-URI/issuer mismatch.
- [ ] oauth2-proxy `email_domains` matches provisioned `@<NODE_ONION>.onion` users; `LDAP_DN_BASE` + CA identity resolve consistently.

### Per-domain TLS

- [ ] Extra domain under `applications.<app>.server.domains` + `tls.mode` deploys as a separate HTTPS vhost (correct flavor) alongside the onion vhost, same upstream.
- [ ] `tls.py` unit tests: onion→forced off; foreign→app-level flavor; unset→`TLS_MODE`.

### Egress

- [ ] `TOR_EGRESS_ENABLED` defaults `false` (outbound untouched); `true` exposes SOCKS to containers, documented.

### CI / E2E

- [ ] CI job: Tor bootstraps, `torsocks curl -I http://<sub>.<NODE_ONION>.onion` returns the app response; retried against transient Tor-network failures; unit tests independent of Tor-network availability.

### Quality

- [ ] Whole flow idempotent (second run: no changes); reloads handler-driven; clear failure if Tor cannot bootstrap.
- [ ] `make test` green tree-wide.
- [ ] README documents: model, mint helper usage, key backup/restore, limitations — no LE for `.onion`; outbound public mail undeliverable from `@onion` senders; fresh-node only (no clearnet migration); extra public domains = per-app opt-in.

## Onion service extensions (phase 2, layered on a green onion core)

These build on the working onion node and are implemented after the web core is verified.

### Mailu listening on the onion (operator: "if possible")

- The node hidden service exposes Mailu's mail ports in addition to `80`, via extra `HiddenServicePort` entries: `HiddenServicePort 25`, `587`, `465`, `143`, `993` → Mailu's local front binds on `127.0.0.1`. Mailu is then reachable at `<node>.onion` for SMTP/submission/IMAP.
- Mechanism: `torrc.j2` renders extra ports from `TOR_ONION_EXTRA_PORTS` (list of `{onion_port, target}`), populated when `web-app-mailu` is deployed. Mailu's front is bound to `127.0.0.1` in the onion node.
- [ ] With Mailu deployed on an onion node, `<node>.onion:993` / `:587` accept connections over Tor; the extra `HiddenServicePort` lines are rendered only when Mailu is present.

### Mail egress over Tor (operator: "must")

- Outbound mail to `.onion` recipient domains is routed through Tor's SOCKS proxy (`127.0.0.1:9050`) instead of clearnet DNS/MX — enabling onion-to-onion / federated mail without public MX/rDNS.
- Mechanism: a Postfix transport for `.onion` next-hops via a SOCKS-aware delivery path (e.g. a `torsocks`-wrapped transport or a SOCKS relay), gated on `svc-net-tor` being active. Public-Internet mail to non-onion domains stays on the normal path.
- [ ] On an onion node, mail addressed to a `*.onion` domain is delivered via the Tor SOCKS proxy; delivery to non-onion domains is unaffected.

### Playwright over Tor (operator: "probably")

- When the target under test is an `.onion` domain, the Playwright browser routes through Tor's SOCKS proxy so specs exercise the real onion path (aligns with Decision #11's real-Tor E2E).
- Mechanism: the `test-e2e-playwright` runner sets the browser proxy to `socks5://127.0.0.1:9050` (with `socks5` remote DNS for `.onion` resolution) when the resolved domain ends in `.onion`.
- [ ] A Playwright spec against a `<sub>.<node>.onion` surface passes through the Tor SOCKS proxy on an onion node; clearnet targets are unaffected.

## Out of scope

Dual clearnet+onion with `Onion-Location` bridge and mirrored SSO realms; per-app dedicated onions / Tor Client Authorization; distributed backups over onion; transparent full-egress torification (only `.onion`-destination mail egress is in phase 2); migration of existing clearnet nodes.

## Validation

```bash
# mint runs during inventory build (sets DOMAIN_PRIMARY), then:
INFINITO_APPS="svc-net-tor,web-app-keycloak,web-app-nextcloud" make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
torsocks curl -I http://next.cloud.<NODE_ONION>.onion   # app over Tor, no public ports
# complete an SSO login over .onion; redeploy; confirm address unchanged
```

## Prerequisites

Read [AGENTS.md](../../AGENTS.md), then [Role Loop](../agents/action/iteration/README.md) and the [Playwright contract](../contributing/artefact/files/role/playwright.specs.js.md). Verify key-file byte formats and vhost/TLS behavior **in the DiD container first**, then redeploy.

## Implementation order

1. Mint helper + unit tests (address vector, formats, idempotency).
2. Role scaffold: Dockerfile, compose, torrc, key restore, volume + backup wiring.
3. `tls.py`/`tls_common`: onion branch + app-level flavor override + unit tests.
4. E2E CI job (torsocks, retries).
5. README + cross-link the implementing PR here.

## Commit Policy

- No `git commit` until every Acceptance Criterion is checked.
- When green, operator runs `git-sign-push` outside the sandbox; the agent MUST NOT push.

## Context

- <https://spec.torproject.org/address-spec> — v3 address + key formats
- <https://www.rfc-editor.org/rfc/rfc7686.html> — `.onion` special-use domain
- <https://gist.github.com/mtigas/565718bbb928ce439e95> — subdomain hidden-service reference
- <https://www.w3.org/TR/secure-contexts/> — `.onion` secure context
- [`roles/svc-ai-ollama/`](../../roles/svc-ai-ollama/) — archetype
- [`plugins/lookup/tls.py`](../../plugins/lookup/tls.py) — TLS resolution
- [`cli/administration/inventory/`](../../cli/administration/inventory/) — mint integration point
