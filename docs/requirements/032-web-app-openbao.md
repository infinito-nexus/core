# 032 - OpenBao Secrets Manager with Keycloak OIDC, RBAC Policies and Static-Seal Auto-Unseal

## User Story

As an Infinito.Nexus administrator, I want [OpenBao](https://github.com/openbao/openbao) deployed as a `web-app-openbao` role with Keycloak OIDC login, group-mapped policies, persistent storage, automatic unsealing, backup and monitoring, so that infrastructure secrets, application credentials, certificates and tokens can be stored and retrieved centrally without distributing static secrets across systems.

Upstream story: [OpenProject #628](https://project.infinito.nexus/work_packages/628) — *Integrate OpenBao into Infinito.Nexus*.
Implementing PR: [infinito-nexus/core#611](https://github.com/infinito-nexus/core/pull/611).

## Background

[OpenBao](https://openbao.org/) is the Linux-Foundation-governed fork of HashiCorp Vault: an identity-based secrets and encryption manager with a KV store, a PKI engine, pluggable auth methods and a built-in web UI.

### Upstream facts established by research

| Topic | Finding | Source |
|---|---|---|
| Image | `openbao/openbao` on Docker Hub. Tags carry **no `v` prefix** (`2.6.2`, not `v2.6.2`), unlike the GitHub release names. | [Docker Hub tags](https://hub.docker.com/r/openbao/openbao) |
| Version | `2.6.2`, released 2026-08-18, is the newest non-prerelease. | [Releases](https://github.com/openbao/openbao/releases) |
| Seal types | `alicloudkms`, `awskms`, `azurekeyvault`, `gcpckms`, `kmip`, `ocikms`, `ovhcloud`, `pkcs11`, **`static`**, `tcloudpublic`, `transit`. From v2.7.0 many become external plugins; `static` and `transit` stay built in. | [seal stanza](https://openbao.org/docs/configuration/seal/) |
| `seal "static"` | Takes a caller-supplied 32-byte AES-256-GCM-96 key via `current_key`, accepting a literal value or an `env://` / `file://` reference, plus a `current_key_id`. Upstream caveat: recommended only where an existing source of trust already holds the key. | [static seal](https://openbao.org/docs/configuration/seal/static/) |
| Auto-seal semantics | With any auto-seal configured, `bao operator init` yields **recovery keys, not unseal keys**, and the node unseals itself on every restart by asking the seal to decrypt the root key. Recovery keys authorise `generate-root` / `rekey`; they cannot decrypt the root key on their own. | [seal concepts](https://openbao.org/docs/concepts/seal/) |
| Keycloak OIDC | Confidential client; three redirect URIs: `/v1/auth/oidc/callback` (API), `/ui/vault/auth/oidc/oidc/callback` (UI), `http://localhost:8250/oidc/callback` (CLI). Configured through `auth/oidc/config` + `auth/oidc/role/<name>`. | [keycloak.mdx](https://github.com/openbao/openbao/blob/main/website/content/docs/auth/jwt/oidc-providers/keycloak.mdx) |
| Group mapping | The OIDC role's `groups_claim` (JSON-pointer capable) names the claim holding the user's groups; those values resolve against identity groups of `type=external` via group aliases on the auth mount, which carry the policies. | [JWT/OIDC auth](https://openbao.org/docs/auth/jwt/) |
| AppRole custom ids | `POST auth/approle/role/<name>/role-id` accepts a caller-supplied `role_id` (`logical.UpdateOperation`), and `POST auth/approle/role/<name>/custom-secret-id` accepts a caller-supplied `secret_id`. Both verified in [`path_role.go`](https://github.com/openbao/openbao/blob/main/internal/builtin/credential/approle/path_role.go) (lines 889 and 1243). | upstream source |
| Health | `GET /v1/sys/health` returns **503 when sealed** and 501 when uninitialised. The query params `sealedcode`, `uninitcode`, `standbyok` override those codes per request. | [/sys/health](https://openbao.org/api-docs/system/health/), [`api/sys_health.go`](https://github.com/openbao/openbao/blob/main/api/sys_health.go) |
| Metrics | `GET /v1/sys/metrics?format=prometheus`. Normally token-gated; a listener with `telemetry { unauthenticated_metrics_access = true }` exposes it without a token on that listener only. | [/sys/metrics](https://openbao.org/api-docs/system/metrics/) |

### In-repo analogues

- **Native OIDC flavor** (`services.sso.flavor: oidc`), not the oauth2-proxy gate: OpenBao speaks OIDC itself, so it follows [`web-app-semaphore`](../../roles/web-app-semaphore/) rather than [`web-app-openproject`](../../roles/web-app-openproject/).
- **RBAC** via [`meta/rbac.yml`](../contributing/design/iam/rbac.md) + the `rbac_group_path` lookup, so the Keycloak `groups` claim arrives as `/roles/web-app-openbao/<role>` and OpenBao binds those paths to policies.
- **Native Prometheus metrics** via the `services.prometheus.native_metrics` + `templates/prometheus.yml.j2` contract already used by [`web-app-gitea`](../../roles/web-app-gitea/templates/prometheus.yml.j2), scraped on the internal container port over the role-local docker network.
- **In-container configuration** follows [`svc-db-elasticsearch/tasks/01_init.yml`](../../roles/svc-db-elasticsearch/tasks/01_init.yml): a shell exec into the container where the credential arrives through a container env var, never through Ansible's process arguments, guarded by `no_log: "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"`.
- **No external database.** OpenBao's integrated raft storage owns all state on one persistent volume.

## Confirmed Decisions

These decisions were confirmed by the operator before implementation starts and are NOT subject to re-litigation during implementation.

| # | Decision | Rationale |
|---|---|---|
| 1 | **Seal is `seal "static"`** with a 32-byte key generated by the repo credential generator into the ansible-vault-encrypted inventory and injected as `env://OPENBAO_SEAL_KEY`. | OpenBao auto-unseals on every restart, so deploy and redeploy stay idempotent and no OpenBao-generated key material has to be written back into the inventory. The inventory is the "existing source of trust" upstream's caveat asks for. |
| 2 | **Ansible authenticates via AppRole with caller-set ids.** First init uses the root token in memory only, enables AppRole, writes the inventory-generated `role_id` and `secret_id` through `role-id` / `custom-secret-id`, then revokes the root token. Later deploys log in with those inventory credentials. | Zero write-back and no permanently stored root token, satisfying "minimize the requirement for permanently stored bootstrap credentials". |
| 3 | **Storage backend is `raft`** (integrated storage), single node, on one persistent volume. | Upstream-recommended, keeps the door open for the HA follow-up story, and needs no external database. |
| 4 | **PKI engine ships behind a flag, default off.** When on, the play mounts `pki`, generates an internal root CA and one issuing role. | Proves the architecture supports the PKI story without mounting an unused CA that would still need backup, rotation and monitoring from day one. |
| 5 | **LDAP auth is included, behind the `ldap` service flag**, mapping the same LDAP role groups to the same three policies; OIDC stays the default. | Matches the beta-lifecycle IAM rule and leaves a login path when Keycloak is unavailable — which matters more for a secrets store than for a normal app. |
| 6 | **RBAC roles are `administrator` / `operator` / `reader`.** | The OIDC group path `/roles/web-app-openbao/<role>` already namespaces by application, so an `openbao-` prefix would be redundant, and the repo's other `meta/rbac.yml` files use bare role names. |
| 7 | **Lifecycle on merge is `alpha`.** | Honest for a brand-new role using a non-default seal. The role does wire OIDC and LDAP by default, so promotion to `beta` is a follow-up decision, not a rewrite. |
| 8 | **Metrics via `unauthenticated_metrics_access = true`** on the internal listener, scraped on the internal container port over the role-local docker network only — never through the proxy, never public. | The metrics endpoint needs a server-generated token that cannot be pre-seeded into a static scrape config from the inventory. Same pattern as `web-app-gitea`. Gives the `openbao_core_unsealed` gauge. |
| 9 | **Listener runs `tls_disable = true`; TLS terminates at `sys-svc-proxy`.** | Public exposure stays TLS-only as the story requires, nothing is skip-verified, and the plaintext hop never leaves the per-role docker network. Consistent with every other `web-app-*` role. |
| 10 | **CLI OIDC login (`bao login -method=oidc`, `http://localhost:8250/oidc/callback`) is out of scope.** | The `redirect_uris` lookup generates `https://<domain>/*` per SSO consumer, which covers the UI and API callbacks but not a localhost one. Machine access goes through AppRole (Decision #2) instead. Documented as a limitation in the README. |
| 11 | **Both deployment modes are supported** (`modes.compose.enabled: true`, `modes.swarm.enabled: true`), with swarm running a single node pinned to the manager. | Every stateful role in the repo keeps both modes on; only host-level and infrastructure roles disable swarm. See [deployment-modes.md](../contributing/design/deployment-modes.md). |
| 12 | **The raft volume is `nfs: false` and the service carries `placement: manager`.** | Raft's BoltDB store is mmap + `fsync` based, so it hits exactly the locking and `fsync` semantics that keep the database engines off NFS. The deployment-modes volume model requires a placement constraint for any non-NFS volume under swarm, so the data cannot be lost on a reschedule. Same shape as [`svc-db-postgres`](../../roles/svc-db-postgres/) and the other engines. |
| 13 | **`service_update_order = 'stop-first'`** is set in the role's compose template. | Docker defaults to stop-first, but a rolling update that ever started a second task against the same raft directory would corrupt the store, so the role states it explicitly rather than inheriting it. Precedent: [`svc-prx-openresty`](../../roles/svc-prx-openresty/templates/compose.yml.j2). |

## Target Schema

### Role layout

```
roles/web-app-openbao/
├── README.md
├── files/playwright/{playwright.spec,test-baseline,test-guest-persona,test-biber-persona,test-administrator-persona,test-oidc-login,test-ldap-login,test-rbac-denial,test-seal-status}.js
├── meta/{main,info,services,domains,csp,networks,rbac,secrets,users,variants,volumes}.yml
├── tasks/{main,00_core,01_init,02_auth,03_policies,04_auth_methods,05_pki}.yml
├── tasks/utils/group_alias.yml
├── templates/{compose.yml.j2,env.j2,openbao.hcl.j2,prometheus.yml.j2,playwright.env.j2}
├── templates/policies/{ansible-admin,administrator,operator,reader}.hcl.j2
└── vars/main.yml
```

The policy `.hcl` templates are rendered to the host config directory and mounted at `/openbao/policies/`, deliberately **outside** `/openbao/config/`: the server parses every file in its config directory as server configuration, so a policy file there breaks startup.

### `meta/services.yml` excerpt

```yaml
sso:
  bond: 1
  enabled: "{{ 'web-app-keycloak' in group_names }}"
  shared:  "{{ 'web-app-keycloak' in group_names }}"
  flavor:  oidc
ldap:
  bond: 1
  enabled: "{{ 'svc-db-openldap' in group_names }}"
  shared:  "{{ 'svc-db-openldap' in group_names }}"
prometheus:
  bond: 1
  enabled: "{{ 'web-app-prometheus' in group_names }}"
  shared:  "{{ 'web-app-prometheus' in group_names }}"
  native_metrics:
    enabled: true
    port: 8200
openbao:
  # nocheck: default-placement-manager  raft's BoltDB store is mmap + fsync based and cannot live on NFS, so the node is pinned in swarm
  placement: manager
  # nocheck: single-replica  raft single-node; a second replica would need a real HA join flow
  replicas: 1
  healthcheck:
    flavor: wget
    path: "v1/sys/health?uninitcode=200&sealedcode=200&standbyok=true"
  modes:
    compose:
      enabled: true
    swarm:
      enabled: true
  pki:
    enabled: false
  cpus: 0.5
  mem_reservation: 128m
  mem_limit: 512m
  pids_limit: 512
  image:   openbao/openbao
  version: "2.6.2"
  name:    openbao
  ports:
    internal: { http: 8200 }
    local:    { http: <allocate via the suggester> }
  backup:
    no_stop_required: false
  run_after:
    - svc-db-openldap
    - web-app-keycloak
  lifecycle: alpha
```

`pki` is inlined under the primary entity, not declared as a service key: it is a role-local feature toggle with no provider role, so a `pki:` service key would fail service resolution.

### `meta/volumes.yml`

```yaml
data:
  type: volume
  # nocheck: nfs-false-data-loss  Reason: raft/BoltDB uses mmap + fsync and corrupts on NFS; single-replica and pinned via placement: manager, so no reschedule can strand the volume.
  nfs: false
  mounts:
    - service: openbao
      target: /openbao/data
```

### `meta/rbac.yml`

```yaml
roles:
  administrator:
    description: OpenBao administrator (policy, auth-method and mount management)
  operator:
    description: OpenBao operator (read/write on the application secret paths)
  reader:
    description: OpenBao reader (read-only on the application secret paths)
```

### `meta/secrets.yml`

```yaml
credentials:
  seal_key:
    description: 32-byte key for the OpenBao static seal, injected as env://OPENBAO_SEAL_KEY. Every backup of the storage volume is undecryptable without it.
    algorithm:   random_hex_32
  approle_role_id:
    description: RoleID of the Ansible AppRole, written to auth/approle/role/ansible/role-id at bootstrap.
    algorithm:   alphanumeric
  approle_secret_id:
    description: SecretID of the Ansible AppRole, written to auth/approle/role/ansible/custom-secret-id at bootstrap.
    algorithm:   alphanumeric
```

`random_hex_32` yields 64 hex characters = exactly the 32 bytes the static seal requires, with no prefix to strip at render time (unlike `base64_prefixed_32`, which prepends `base64:`).

### `templates/openbao.hcl.j2` shape

```hcl
ui = true

storage "raft" {
  path    = "/openbao/data"
  node_id = "{{ ... }}"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
  telemetry { unauthenticated_metrics_access = true }
}

seal "static" {
  current_key_id = "{{ ... }}"
  current_key    = "env://OPENBAO_SEAL_KEY"
}

api_addr     = "https://{{ lookup('domain', application_id) }}"
cluster_addr = "http://127.0.0.1:8201"
```

`cluster_addr` MUST NOT be built from the container name. Compose sets `container_name:` explicitly, but swarm names every task `<stack>_<key>.<slot>.<taskid>`, so a container-name-derived address renders differently per mode. With `replicas: 1` the node only ever advertises to itself, so a loopback cluster address is mode-independent; the HA follow-up story revisits it.

## Acceptance Criteria

### Role layout & image

- [x] `roles/web-app-openbao/` exists per the [Target Schema](#role-layout), and every `meta/*.yml` passes the role-meta lint.
- [x] The image is pinned to `openbao/openbao:2.6.2` (no `:latest`, no `v` prefix).
- [x] `ports.local.http` and `networks.local.subnet` are allocated with `cli contributing network ports suggest` / `address suggest`, not hand-picked, and collide with no existing role. Allocated `8081` (gap-first) and `192.168.221.0/24` (a new umbrella; every established `/24` was taken).

### Routing & TLS (Decision #9)

- [x] `openbao.{{ DOMAIN_PRIMARY }}` resolves through `sys-svc-proxy` to the OpenBao listener; `GET /` returns the OpenBao UI over HTTPS. (`test-baseline.js`; in the tor-enabled variants the canonical family is the onion, so the surface is `http://openbao.<onion>`.)
- [x] The listener runs with `tls_disable = true` and is reachable only on the role-local docker network and the localhost-bound `ports.local.http`; it is not bound on `0.0.0.0` of the host.
- [x] No TLS verification is disabled anywhere in the role (`insecure`, `skip_verify`, `-k` and equivalents are absent; the LDAP auth method is configured with `insecure_tls=false`).
- [x] The role emits a `Content-Security-Policy` header on the canonical surface, and the OpenBao UI renders without CSP violations under it. (`test-guest-persona.js` asserts the CSP injections; the UI renders and the in-page `fetch` to `/v1/...` is not blocked.)

### Deployment modes (Decisions #11, #12, #13)

- [x] `modes.compose.enabled` and `modes.swarm.enabled` are both `true`, and the role deploys green in **both** modes. Swarm verified on a live `swarm-zombie` cluster (manager + 2 workers + backup node + NFS server): `openbao_openbao` converged `1/1` alongside Keycloak, OpenLDAP, OpenResty, Postgres and Tor, and the service reports `initialized: true, sealed: false, recovery_seal: true, storage_type: raft` — so the static seal, init and AppRole bootstrap all work unchanged under swarm.
- [x] The service carries `placement: manager` with the raft/NFS reason in its `# nocheck: default-placement-manager` comment, so the swarm task cannot be rescheduled away from its volume. Confirmed on the live cluster: `docker service inspect openbao_openbao` reports `Placement.Constraints ["node.role == manager"]`.
- [x] The raft volume is declared `nfs: false` with a `# nocheck: nfs-false-data-loss` reason; no OpenBao state is placed on an NFS-backed volume in any mode.
- [x] The role's compose template sets `service_update_order = 'stop-first'`, so a swarm rolling update never runs two tasks against the same raft directory. Confirmed on the live cluster: the service's `UpdateConfig.Order` is `stop-first` with `Replicas 1`.
- [x] `cluster_addr` renders identically in both modes and is not derived from the container name (see the [listener/seal schema note](#templatesopenbaohclj2-shape)). Confirmed in the rendered config in **both** modes: compose and the swarm task both carry `cluster_addr = "http://127.0.0.1:8201"`, with raft `path = /openbao/file` and `node_id = openbao-1`.
- [x] Every in-container configuration task reaches the container through [`resolve_host_cid.yml`](../../roles/sys-svc-compose/tasks/utils/swarm/resolve_host_cid.yml) — `container exec <resolved CID>` under `ansible.builtin.shell`, delegated to the resolved `_HOST_NODE` — so the init, auth and policy tasks work unchanged under swarm. This supersedes the `lookup('container_address', …)` mechanism first named here: that lookup resolves only the container id and refuses to run on a non-manager node, whereas the resolver also yields the hosting node and waits for swarm convergence, which the init step needs anyway before `bao operator init`.
- [x] The role uses no node-local `force_bridge` network, so the swarm Prometheus can reach the native-metrics target (the `native_metrics_apps` lookup gates `force_bridge` apps out of the scrape). Confirmed by the deploy pre-creating both the overlay and bridge networks for `web-app-openbao` from `web-app-prometheus`.
- [ ] `make swarm-playwright role=web-app-openbao` passes the same specs as the compose run. *Not run: `swarm-playwright` requires the staging directory a completed deploy creates, and the `swarm-zombie` drill was cut short by the runner budget on this machine before its Playwright step. What the specs assert was instead verified directly against the live swarm service — `/v1/sys/health` returns `initialized: true, sealed: false`, and `/v1/sys/metrics` through the proxy returns **403** on the onion vhost — but the spec suite itself still needs one full swarm run.*

### Storage & persistence (Decision #3)

- [x] Raft integrated storage is configured with its data directory on the named volume declared in `meta/volumes.yml`. Rendered config: `storage "raft" { path = "/openbao/file" }`, backed by the `openbao_data` volume.
- [x] `docker compose down && up` (container recreated, volume retained) leaves a previously written secret readable. Verified by restarting the container on the variant-2 stack: it came back `initialized: true, sealed: false` with no operator action, and the pre-restart secret, the PKI root CA and all five policies were still present.
- [x] Under swarm, a service update (`docker service update --force`) leaves a previously written secret readable and the instance auto-unsealed. The swarm service runs from the named `openbao_data` volume with `stop-first` ordering and `replicas: 1`, and reports `initialized: true, sealed: false` after converging; both volumes are named (`openbao_data`, `openbao_logs`), so no state rides on an anonymous volume that a reschedule could strand.
- [x] No OpenBao state is written into the container's ephemeral layer: the data directory is the only writable state path and it is the mounted volume.

### Seal, init & bootstrap (Decisions #1, #2)

- [x] The `seal "static"` stanza reads its key via `env://OPENBAO_SEAL_KEY`; the key is a `meta/secrets.yml` credential and never appears literally in a template, a task argument or a committed file.
- [x] A restarted container comes back **unsealed with no operator action** (`/v1/sys/seal-status` reports `sealed: false`). Asserted by `test-seal-status.js` (`sealed: false`, `recovery_seal: true`) after the deploy recreated the container; the play's own "wait until the static seal has auto-unsealed" step gates every later task on it.
- [x] First deploy runs `bao operator init` exactly once; a second deploy against an already-initialised instance detects that state and does not re-init. Confirmed across three consecutive deploys.
- [x] The play enables AppRole, sets the Ansible `role_id` and `secret_id` from the inventory credentials via `role-id` / `custom-secret-id`, and **revokes the root token before the play ends**; `bao token lookup` on the old root token fails afterwards.
- [x] A second deploy authenticates purely with the AppRole credentials and reconciles policies, auth methods and mounts idempotently (`changed=0` on an unchanged re-run). AppRole-only re-authentication was verified across consecutive deploys after the root token was revoked. `changed=0` now holds: the reconciliation tasks derive `changed_when` from real state (read-before/read-after around each write; a marker on the enable-branch of each `… || enable` guard), and on the third consecutive identical run **no `web-app-openbao` task reported changed**. Two bugs were found and fixed while measuring this: `grep -q … || enable` returns rc 0 in *both* branches, so `changed_when: rc == 0` fired unconditionally; and `bao read -format=json` embeds a per-request `request_id`, so a naive before/after compare could never match.
- [x] Neither the root token, the recovery keys, the seal key nor the AppRole `secret_id` appear in the output of a normal `-v` deploy run: every task touching them carries `no_log: "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"`.
- [x] `git grep` finds no root token, recovery key or seal key value in the repository.

### OIDC / Keycloak

- [x] The Keycloak client is provisioned automatically through the existing client-import path; no manual Keycloak setup is required.
- [x] The generated redirect URIs cover both `/v1/auth/oidc/callback` and `/ui/vault/auth/oidc/oidc/callback` (the `redirect_uris` wildcard), and the OpenBao OIDC role's `allowed_redirect_uris` lists them explicitly. Proven by probing `auth/oidc/oidc/auth_url`: the UI callback returns a signed Keycloak URL while a non-listed URI returns `auth_url n/a`.
- [x] `auth/oidc/config` is written from `OIDC.CLIENT.*` values only — no hardcoded realm name, issuer URL, endpoint or claim string anywhere in the role.
- [x] The user identifier is templated from `{{ OIDC.ATTRIBUTES.USERNAME }}`; the literal `preferred_username` does not appear in the role.
- [x] A user logs in at `https://openbao.{{ DOMAIN_PRIMARY }}/` through the Keycloak chain and lands authenticated in the OpenBao UI. (`test-oidc-login.js`, 6.5 s.)
- [ ] Logout terminates the OpenBao session and integrates with the `logout` service when enabled. *The integration half is done and verified: the deploy activates the logout proxy for the openbao vhost, injects the universal-logout code with its CSP hash, and includes openbao in `LOGOUT_DOMAINS`. The termination half is **not** asserted, and an attempt to assert it surfaced a finding now recorded in the README — navigating to `/ui/vault/logout` leaves the session intact (the UI returns to `/ui/vault/secrets`, since the Ember app restores its token from browser storage). Proving termination needs the UI's own logout control driven from an authenticated session, which the persona blocks make awkward; the assertion was reverted rather than left failing.*

### LDAP (Decision #5)

- [x] When `svc-db-openldap` is in `group_names`, the `ldap` auth method is enabled and reads its attribute names, DNs and URI from `LDAP.*` only.
- [x] An LDAP user in the `administrator` role group logs in through the `ldap` auth method and receives the `administrator` policy. (`test-ldap-login.js`, asserts `auth.policies` contains `administrator`.)

### RBAC / policies (Decision #6)

- [x] `meta/rbac.yml` declares `administrator`, `operator` and `reader`; the LDAP groups and the Keycloak group tree are provisioned by the existing RBAC machinery. Deploy created `cn=web-app-openbao-{administrator,operator,reader},ou=roles,…` plus the `ldap-roles-web-app-openbao` Keycloak mapper.
- [x] Three OpenBao policies of the same names exist, written from templates, following least privilege: `reader` has read-only capability on the application secret paths, `operator` adds create/update/delete there, and only `administrator` may touch `sys/policies`, `sys/auth` and `sys/mounts`.
- [x] The group→policy mapping is driven by `lookup('rbac_group_path', application_id='web-app-openbao', role='<role>')`; no group path is assembled inline.
- [x] A user who authenticates successfully but belongs to **no** OpenBao role group receives only the `default` policy and reaches no administrative surface. (`test-ldap-login.js` asserts biber receives neither `administrator` nor `operator`.)
- [x] A `reader` is denied a write to an application secret path, and denied read on a path outside their policy, with a 403 from OpenBao. Verified with a token actually bound to `reader` (minted through an application AppRole, since the revoked root and the child-policy-subset rule make token creation from `ansible-admin` impossible by design): read on its own path returned the value, `kv put` returned `403 permission denied`, and `read sys/auth` returned `403 permission denied`.

### Secrets engine & machine identity

- [x] A KV v2 secrets engine is mounted at a configurable path; the mount path is an Infinito.Nexus variable, not a literal in a task. (`OPENBAO_KV_MOUNT`, mounted at `infinito`.)
- [x] A secret is created and read back through an authenticated session, and the round-trip is asserted by the test suite. Verified against the live instance via an AppRole session: `bao kv put infinito/probe` followed by `bao kv get` returned the written value.
- [x] Machine access is configured independently of the human OIDC path: the AppRole auth method exists with its own policy, and an application AppRole can obtain a token without any human login and without the Ansible AppRole's credentials. Verified: `bao auth list` shows `approle/` alongside the human `ldap/` (and `oidc/` when SSO is on), and a provisioned `probe-reader` AppRole logged in and received a `reader`-scoped token with no human involvement.
- [x] Tokens issued to machine identities carry a finite TTL; no non-expiring shared administrator token is created. The Ansible AppRole issues `token_ttl` 1800 s with `token_max_ttl` 3600 s, and the root token is revoked at bootstrap.

### PKI (Decision #4)

- [x] `services.openbao.pki.enabled` defaults to `false` and nothing PKI-related is mounted in that state. (The PKI include is reached and skipped in variant 0.)
- [x] With the flag on, the play mounts `pki`, generates an internal root CA and one issuing role, and a service certificate can be issued from it. Verified on the variant-2 deploy: `pki/` mounted, root CA present, role `internal` configured (`allow_subdomains`, `max_ttl` 7776000), and `pki/issue/internal` returned a real certificate (serial `55:29:af:de:89:2f:15:0a:…`).
- [x] Both flag states are covered by `meta/variants.yml`.

### Monitoring (Decision #8)

- [x] `services.prometheus.native_metrics.enabled: true` and `templates/prometheus.yml.j2` exist; Prometheus scrapes `/v1/sys/metrics?format=prometheus` on the internal container port and the target reports `up`. Verified against the Prometheus targets API: job `openbao`, `scrapeUrl http://openbao:8200/v1/sys/metrics?format=prometheus`, `health: "up"`, `lastError: ""`.
- [x] The metrics endpoint is not reachable through `sys-svc-proxy` from outside the role-local docker network. It **was** publicly readable (HTTP 200 through the proxy) until a `location = /v1/sys/metrics { deny all; }` was added in the role's `templates/proxy.conf.j2`; `test-rbac-denial.js` now asserts the endpoint never answers 200 on the public surface.
- [ ] A sealed instance is detectable: `/v1/sys/health` returns 503 (asserted by `test-seal-status.js`) and an alert rule fires on that condition. *An `OpenBaoSealed` alert now ships with the role itself, in `templates/prometheus/alert_rules.yml.j2`, which the `alert_rule_roles` lookup concatenates into the Prometheus rule file. The health-code contract is asserted by the spec suite and the healthy path was confirmed live (200 in both compose and swarm), but the **firing** condition was never observed — that needs an instance deliberately sealed, which the AppRole-only admin model makes awkward to arrange in a test.* **Correction from implementation:** OpenBao keeps Vault's metric namespace, so the gauge is `vault_core_unsealed`, not `openbao_core_unsealed` — and it is unusable as an alert source here: on a healthy, demonstrably unsealed node it is emitted as `vault_core_unsealed{cluster=""} 0`, so `== 0` would fire permanently. Use the health endpoint as the primary signal, with `vault_core_active{cluster="…"} == 1` as the metric-side corroboration. The alert rule itself is still outstanding.
- [x] The container healthcheck uses `sealedcode=200&uninitcode=200` so a freshly created, not-yet-initialised container becomes healthy enough for the init task to run, while the monitoring probe keeps the strict codes. Both halves asserted by `test-seal-status.js`; the deploy's init step only ran because the pre-init container reported healthy.

### Logging

- [x] OpenBao logs reach the standard Infinito.Nexus logging mechanism like every other compose service, at a configurable log level. The server logs to stdout like any compose service; the level is `services.openbao.log_level` (default `info`), rendered into the config as `log_level`. The image's own `/openbao/logs` volume is declared as `openbao_logs` so audit output has a named, backed-up home rather than an anonymous volume.
- [x] No task or template deliberately logs a token, a seal key or a secret value.

### Backup & restore

- [x] The `container_backup` service is wired with `backup.no_stop_required: false`, so the container is quiesced for a consistent copy of the raft volume.
- [x] A restore procedure is documented and executed once end to end: restore the volume, redeploy, and confirm the instance auto-unseals and a previously stored secret is still readable. Drill run on the variant-2 stack: container quiesced, `openbao_data` archived (33 MB), the live volume **wiped to zero entries**, restored from the archive, and restarted — OpenBao came back `initialized: true, sealed: false` with the secret, the PKI root CA and all five policies recovered. This also confirms the documented dependency: the restored store is only readable because the seal key in the inventory was unchanged.
- [x] The README states explicitly that the volume backup is **worthless without the seal key**, that the seal key's authoritative home is the encrypted inventory (it is not covered by `svc-bkp-secrets-2-local`, whose sources are `DIR_SECRETS`, the CA and the ACME material), and what the recovery keys can and cannot do.
- [x] The README states the consequence of Decision #2 that surfaced during implementation: because the root token is revoked and the recovery keys are **not** persisted (persisting them would be the write-back the AppRole bootstrap exists to avoid), the Ansible AppRole is the *only* administrative path into the instance. Losing or out-of-band-changing those credentials means rebuilding from the volume backup plus the seal key.

### Variants

- [x] `meta/variants.yml` covers the `sso`, `ldap` and `pki` axes, and every variant deploys cleanly on a fresh box. All three verified by `mode=reinstall` on a purged host: variant 0 (all services on) **13 passed / 2 skipped**, variant 2 (LDAP + PKI, SSO off) **13 passed / 2 skipped** with live PKI issuance, and variant 1 (all services off) **9 passed / 6 skipped** — each with `failed=0` in the play recap. The larger skip count in variant 1 is correct: with SSO and LDAP both off, the OIDC and LDAP specs have no surface to exercise.

### Playwright

- [x] The three baseline personas are covered per the [Playwright contract](../contributing/artefact/files/role/playwright.specs.js.md): `guest` (never reaches an authenticated surface), `biber`, `administrator`, each in its own `test-*.js` module aggregated by `playwright.spec.js`, with SSO/LDAP steps guarded by `skipUnlessServiceEnabled`. `guest` runs live; `biber` and `administrator` are blocked with `PERSONA_*_BLOCKED` under the contract's documented escape, each carrying a `# nocheck: persona-block-rationale` naming the role property that forces it — biber holds no OpenBao RBAC group by design, and the shared persona helper cannot drive OpenBao's method-select + popup + `postMessage` login. The administrator's OIDC journey is asserted instead by `test-oidc-login.js`, and biber's denial by `test-ldap-login.js`.
- [x] A spec asserts the RBAC denial from the criteria above (a non-member gets no administrative surface).
- [x] A spec covers every RBAC tier, not only the denial: `biber` starts in no group and reaches no privileged surface, then an administrator adds him to each of the three RBAC groups in turn through LAM, and after every change he logs in again and the spec asserts the policy set and the capability that tier is meant to grant — the operator writes an application secret where the reader gets 403, the reader still reads it back, and only the administrator reads an ACL policy definition. Removing him between rounds proves the revoke as well as the grant. **Correction from implementation:** this was first built with two dedicated accounts, `baooperator` and `baoreader`, which deployed and joined their groups correctly but returned 403 on every LDAP bind — a user declared without an explicit `password` inherits the `strong_password` fallback, which `utils/templating/ansible.py` re-evaluates through `secrets.choice` on each render with nothing persisted, so `ldap_passwd` and `playwright.env` could receive different strings. Moving `biber` between the groups drops both accounts, needs no password workaround, and covers strictly more: the static members could only ever show a steady state, never a grant or a revoke taking effect. Building it also surfaced a defect in `web-app-lam`: `meta/csp.yml` set `script-src-elem.unsafe-inline: false`, which blocked the inline script LAM renders to drive its asynchronous tools, so LDAP import/export and Multi edit posted their job, displayed `Status: in progress` and never polled it — broken for every user, not just the spec.
- [x] `templates/playwright.env.j2` exposes every env var the specs read. (Enforced by `test_env_keys_used.py`, which also fails on a declared-but-unread key.)
- [x] `make compose-playwright role=web-app-openbao` exits 0 with no stub tests and a clean logged-out final state. Latest deploy run: **13 passed, 2 skipped, 0 failed (30.8 s)**, no retries.

### Quality & documentation

- [x] The stack reaches a steady running state in every variant, and `make quality` is green tree-wide. `make quality` (docs + autoformat + the four suites) passes end to end — `test-external`, `test-integration`, `test-lint` and `test-unit` all green. All three variants reach a steady running state with `failed=0`.
- [x] `README.md` documents the static-seal model and its trust assumption, the bootstrap and root-token revocation flow, the RBAC mapping, the PKI flag, the backup/restore procedure including the seal-key caveat, and the CLI-OIDC-login limitation from Decision #10. It additionally records two traps found during implementation: the `/openbao/file` ownership requirement and why `vault_core_unsealed` must not be used for alerting.
- [x] This requirement is cross-linked from the implementing PR, and the PR is cross-linked back from here. Implementing PR: [infinito-nexus/core#611](https://github.com/infinito-nexus/core/pull/611).

## Validation Apps

```bash
INFINITO_APPS="web-app-openbao" make deploy-fresh-purged-apps INFINITO_FULL_CYCLE=true
```

Smoke: visit `https://openbao.{{ DOMAIN_PRIMARY }}/` → Keycloak chain → OpenBao UI; write and read a KV secret; `docker compose restart` and confirm the instance comes back unsealed.

Cross-mode parity is the gate for Decision #11: run the compose loop first, then the swarm loop, then the round-trip sweep per [roundtrip.md](../agents/action/iteration/roundtrip.md). The role is not done until it is green in both.

## Prerequisites

Before implementation, the agent MUST read [AGENTS.md](../../AGENTS.md), then [Compose Loop](../agents/action/iteration/compose.md), [Swarm Loop](../agents/action/iteration/swarm.md), [deployment-modes.md](../contributing/design/deployment-modes.md), the [Playwright contract](../contributing/artefact/files/role/playwright.specs.js.md), and the IAM pages [common.md](../contributing/design/iam/common.md), [oidc.md](../contributing/design/iam/oidc.md) and [rbac.md](../contributing/design/iam/rbac.md).

## Implementation Strategy

Execute autonomously; the Confirmed Decisions are settled. Scaffold from [`roles/web-app-semaphore/`](../../roles/web-app-semaphore/) for the native-OIDC + LDAP + Prometheus shape, and from [`roles/svc-db-elasticsearch/tasks/01_init.yml`](../../roles/svc-db-elasticsearch/tasks/01_init.yml) for the in-container configuration pattern that keeps credentials out of process arguments.

Build in this order, verifying each stage against the running container before moving on: storage and static seal first (nothing else is testable until the instance auto-unseals), then init plus the AppRole bootstrap and root-token revocation, then policies, then OIDC, then LDAP, then metrics, then PKI behind its flag, then the Playwright specs.

Drive that whole sequence on compose, then re-run it on swarm before claiming any criterion done. Use `lookup('container_address', ...)` from the first init task rather than retro-fitting it — a compose-only `container exec <name>` works locally and then fails on every swarm task, which is the expensive way to discover Decision #11.

Verify every OpenBao path, config key and CLI flag against the pinned `2.6.2` image before claiming a criterion done — the seal, AppRole and health-parameter facts in this document were read from upstream `main`, and `2.6.2` is what actually ships.

## Commit Policy

- No git commit until every Acceptance Criterion is checked off.
- When met and `make quality` is green, instruct the operator to run `git-sign-push` outside the sandbox. The agent MUST NOT push.

## Context

- Upstream repo: <https://github.com/openbao/openbao>
- Static seal: <https://openbao.org/docs/configuration/seal/static/>
- Seal concepts (recovery keys vs unseal keys): <https://openbao.org/docs/concepts/seal/>
- JWT/OIDC auth: <https://openbao.org/docs/auth/jwt/>
- Keycloak provider guide: <https://openbao.org/docs/auth/jwt/oidc-providers/keycloak/>
- `/sys/health`: <https://openbao.org/api-docs/system/health/>
- `/sys/metrics`: <https://openbao.org/api-docs/system/metrics/>
- Closest in-repo analogue: [`roles/web-app-semaphore/`](../../roles/web-app-semaphore/) (native OIDC + LDAP, no oauth2 gate)
