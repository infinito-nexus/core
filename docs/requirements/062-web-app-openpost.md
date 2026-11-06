# 062 - OpenPost Publishing Desk Role

## User Story

As an Infinito.Nexus PR manager, I want a self-hosted [OpenPost](https://github.com/getopenpost/openpost) publishing desk deployed as the `web-app-openpost` role behind Keycloak single sign-on so that I can compose, schedule and publish content to Fediverse and commercial social networks from one sovereign interface.

## Background

This requirement implements the publishing half of the OpenProject user story "sovereign social media publishing and crossposting" (story criteria AC1, AC2, AC3, AC4, AC6, AC7 and the desk part of AC8).
Automated crossposting from Fediverse accounts (story criterion AC5 and its tests) is specified in [063-openpost-crossposter.md](063-openpost-crossposter.md), which builds on this role.
OpenPost is self-hosted and integrated like every other application of the stack: the official upstream image, configured through environment variables, wired into the shared proxy, Keycloak, Postgres, object storage and backups.

### Evaluation and selection

| Candidate | Verdict | Decisive evidence |
|---|---|---|
| [OpenPost](https://github.com/getopenpost/openpost) | Selected | Only candidate that publishes to Mastodon (any instance), Pixelfed and PeerTube as well as Facebook, Instagram, X, YouTube, LinkedIn, Threads, TikTok and Bluesky. One image, Postgres, S3 media, OIDC with issuer discovery, AES-256-GCM encryption of provider tokens. |
| [Postiz](https://github.com/gitroomhq/postiz-app) | Rejected | No Pixelfed or PeerTube code, one Mastodon instance per deployment, provider tokens stored in plaintext, Temporal plus Elasticsearch required, OIDC without discovery that self-registers users even with registrations disabled, 19 published advisories. |
| [Ferryman](https://ferryman.io/) | Reference only | Closed SaaS without self-hosting, no Pixelfed or PeerTube, no named legal entity in its privacy policy. |
| [Mixpost](https://mixpost.app/) Pro | Rejected | Commercial source-available licence, no PeerTube, image and database support unverified. |
| [TryPost](https://github.com/trypostit/trypost) | Rejected | No published image, no documented SSO, major version churn within weeks. |
| [n8n](https://n8n.io/) | Not a desk | Automation engine only, Sustainable Use License, native OIDC is a paid feature. |

OpenPost carries known risks that this requirement mitigates rather than ignores: it was created on 2026-03-21, one maintainer wrote about 95% of its commits, it shipped 265 releases by 2026-10-20, only the latest release receives security fixes, and its maintainer states that no posting option has passed the project's own live certification yet ([provider reference](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/docs/reference/providers/index.md)).

### Upstream facts established by research

All OpenPost source references point at commit `0deadaf7`, the branch head on 2026-10-20; the latest published release is `v7.22.9`.

| Topic | Finding | Source |
|---|---|---|
| Image | `ghcr.io/getopenpost/openpost` publishes release tags for amd64 and arm64; the image runs as UID 1000 on Alpine and ships a HEALTHCHECK on `/api/v1/health`. | [Dockerfile](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/deploy/docker/Dockerfile) |
| Processes | One binary with the roles `all`, `web`, `worker` and `migrate`; Postgres job claiming uses `FOR UPDATE SKIP LOCKED`, migrations take an advisory lock. | [worker.go](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/server/internal/queue/worker.go) |
| Database | SQLite or Postgres; no MariaDB, no Redis. | [database.go](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/server/internal/database/database.go) |
| Media | Local disk or S3 (`OPENPOST_S3_*`); Facebook, Instagram and TikTok fetch media from public HTTPS URLs. | [.env.example](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/.env.example) |
| App URL | `OPENPOST_APP_URL` MUST carry a real domain, because OpenPost derives the WebAuthn relying-party ID from it and refuses to start otherwise; cookie sessions additionally require a same-origin `Origin` header. | Proof run on 2026-10-21 (see [Egress proof](#egress-proof)) |
| SSO | One instance-wide OIDC provider (`OPENPOST_OIDC_ISSUER`, `_CLIENT_ID`, `_CLIENT_SECRET_FILE`, `_SCOPES`, `_JIT_ENABLED`, `_BOOTSTRAP_ALLOWLIST`, `OPENPOST_SSO_BREAK_GLASS_EMAILS`); identities match on issuer and subject; `groups` and `preferred_username` are not consumed. | [.env.example](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/.env.example), [identity/service.go](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/server/internal/services/identity/service.go) |
| Proxy auth | Trusted-proxy mode accepts `X-OpenPost-Proxy-User` together with `OPENPOST_PROXY_AUTH_SECRET`. | [proxyauth middleware](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/server/internal/services/proxyauth/middleware.go) |
| Secrets at rest | Provider tokens and secrets use AES-256-GCM with key IDs and rotation; JWT, encryption and media signing keys accept `_FILE` variants. | [encrypt.go](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/server/internal/services/crypto/encrypt.go) |
| Telemetry | Diagnostics to `app.openpo.st` are on by default (`OPENPOST_DIAGNOSTICS_ENABLED`), the update check is on (`OPENPOST_UPDATE_CHECK_ENABLED`), public profiles are on (`OPENPOST_PUBLIC_PROFILES_ENABLED`), PostHog telemetry is off (`OPENPOST_TELEMETRY_ENABLED`). | [diagnostics.md](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/docs/reference/configuration/diagnostics.md) |
| Egress guard | `netguard` is OpenPost's SSRF protection: it rejects a destination when any resolved address lies in a private, loopback, CGNAT, link-local, documentation, benchmarking, multicast or reserved range, checks again at connect time and on every redirect, ignores proxy variables, and has no switch for built-in providers. | [netguard.go](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/server/internal/netguard/netguard.go) |
| Guard exceptions | Only operator configuration may reach private addresses: the instance OIDC issuer and custom connectors with `mode: private_allowlist`; built-in provider URLs entered by users never may. Custom CAs are honoured through `SSL_CERT_FILE` and the Go `SSL_CERT_DIR` lookup. | [environment-variables.md](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/docs/reference/configuration/environment-variables.md), [custom-connectors.md](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/docs/reference/configuration/custom-connectors.md) |
| Providers | Mastodon (any instance, out-of-band code, `https` on port 443 only), Pixelfed, PeerTube (password exchanged once for tokens), Bluesky (app password), Facebook Pages, Instagram, Threads, X, YouTube, LinkedIn and TikTok; X, LinkedIn and Threads use env triples, Facebook, Instagram, YouTube and TikTok use `OPENPOST_PROVIDER_APPS`. | [.env.example](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/.env.example) |
| API | REST API with `Idempotency-Key`, publications with per-account renditions, `schedule`, `publish-now`, `retry-failed`, job polling and API tokens. | [openapi.json](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/apps/web/openapi.json) |
| Cost control | `OPENPOST_X_MONTHLY_BUDGET_MICROUSD` and per-post cost settings cap X spending. | [.env.example](https://github.com/getopenpost/openpost/blob/0deadaf7bbf3b3be045e783c3eeef323c9e3c440/.env.example) |

### Egress proof

Inside the development stack, sibling domains such as `*.infinito.test` resolve to the private stack address, and in split-horizon or WireGuard deployments they resolve to private or mesh addresses (`NETWORK_MESH_POOL` is `10.100.0.0/16`), so the unmodified image refuses them.
A role-local egress relay solves this without touching OpenPost: OpenPost reaches the deployment's sibling vhosts through network aliases on a Docker network whose subnet lies outside the guard's ranges, and the relay forwards the untouched TLS stream by SNI to the shared proxy.
The design was proven on 2026-10-21 against the unmodified `ghcr.io/getopenpost/openpost:v7.22.9` with an `nginx:1.30.6-alpine` stream relay on `192.88.99.0/24` (the deprecated 6to4 relay anycast block, RFC 7526) in the compose development stack:

| Check | Observed result |
|---|---|
| Aliased name forwarded to a Mastodon stub | Mastodon app registration succeeded; the stub received `POST /api/v1/apps` for `microblog.infinito.test`. |
| Aliased name forwarded to the real shared proxy by address | TLS verified against the platform CA through OpenResty; the vhost answered HTTP 404 because it is not a Mastodon instance. |
| Sibling name resolved through normal DNS to the stack address | Rejected: "resolves to a private or local address". |
| Private alias and private IP literal | Rejected by the guard. |
| Aliased name missing from the relay's SNI map | Refused by the relay. |

### Platform constraints

| Network | Access path for one organisation | Publish quota | Cost (October 2026) | Token upkeep | Constraint |
|---|---|---|---|---|---|
| Facebook Pages | Own Meta Business app; Standard Access for app-role users without App Review | Reels: 30 per Page per 24 h | No fee found | Long-lived Page tokens do not expire | Development-mode posts are visible only to app-role users |
| Instagram | Professional account via Facebook Login or Instagram Login | 100 per 24 h | No fee found | Instagram Login tokens last 60 days and refresh | JPEG only, fetched from a public URL |
| X | Developer app with prepaid credits | 100 per 15 min per user | $0.015 per post, $0.20 per post with a URL | OAuth 2.0 access tokens refresh via `offline.access` | Identical content across own accounts is forbidden |
| YouTube | Google OAuth client in production status | 100 `videos.insert` calls per day | No fee found | Testing-status refresh tokens expire after 7 days | Private-upload rule for unverified projects is contradictory |
| LinkedIn | Community Management API with legal-entity vetting | Development tier: 500 calls per app per day | No fee found | 60-day tokens without refresh | Human re-authorisation every 60 days |
| Threads | Meta app with `threads_content_publish` | 250 per 24 h | No fee found | 60 days, refreshable | 500 characters per post |
| TikTok | Content Posting API plus audit | About 15 per creator per day | No fee found | Not researched | In-house upload tools are an unacceptable use case |
| Bluesky | App password or atproto OAuth | About 1,666 creates per hour | No fee found | Up to 180 days | Already reachable through `web-app-bridgy-fed` |

Sources:

- [X pricing](https://docs.x.com/x-api/getting-started/pricing)
- [Meta access levels](https://developers.facebook.com/docs/graph-api/overview/access-levels) <!-- nocheck: url -->
- [Instagram publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing) <!-- nocheck: url -->
- [YouTube quota costs](https://developers.google.com/youtube/v3/determine_quota_cost)
- [LinkedIn app review](https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review)
- [TikTok content sharing guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines)
- [Bluesky rate limits](https://docs.bsky.app/docs/advanced-guides/rate-limits)

### In-repo analogues

- [`web-app-nextcloud`](../../roles/web-app-nextcloud/), [`web-app-mastodon`](../../roles/web-app-mastodon/), [`web-app-fider`](../../roles/web-app-fider/), [`web-app-penpot`](../../roles/web-app-penpot/) and [`web-app-discourse`](../../roles/web-app-discourse/) relax their own SSRF guards through native switches; OpenPost has none for built-in providers, which is why the relay exists.
- [container_extra_hosts.py](../../plugins/lookup/container_extra_hosts.py) already resolves the address that reaches the shared proxy per deploy mode for the SSO back-channel pin; the relay forwards to the same address.
- [`svc-net-wireguard`](../../roles/svc-net-wireguard/) carries swarm overlay traffic inside its `swarm` mesh, so the role's overlay network is tunnelled without extra configuration.
- [`web-app-semaphore`](../../roles/web-app-semaphore/) consumes Keycloak through `sso.flavor: oidc`.
- [`web-app-mastodon`](../../roles/web-app-mastodon/), [`web-app-pixelfed`](../../roles/web-app-pixelfed/) and [`web-app-peertube`](../../roles/web-app-peertube/) provide the local Fediverse accounts used as publishing targets in tests.
- [`web-app-seaweedfs`](../../roles/web-app-seaweedfs/) provides S3 object storage through the `seaweedfs` service with `public: true`, as in `web-app-mastodon`.
- [18_api.yml](../../group_vars/all/18_api.yml) is the central SPOT for proprietary API credentials, read through `lookup('api', ...)` and gated by `lookup('api_enabled', ...)`.

## Confirmed Decisions

These decisions were confirmed by the operator before implementation starts and are NOT subject to re-litigation during implementation.

| # | Decision | Reason |
|---|---|---|
| 1 | OpenPost is the publishing desk. | Only candidate covering every required source and target network. |
| 2 | Role id `web-app-openpost`, canonical domain `publish.{{ DOMAIN_PRIMARY }}`. | `social.{{ DOMAIN_PRIMARY }}` belongs to `web-app-friendica`. |
| 3 | The role runs the official `ghcr.io/getopenpost/openpost` image unmodified, pinned to a release tag and configured through environment variables only. | The application is integrated like every other role; the project does not maintain OpenPost. |
| 4 | OpenPost reaches the deployment's own sibling vhosts only through an always-on, role-local egress relay on the role network `192.88.99.0/24` (declared in `meta/networks.yml`, listed in `NETWORK_ROLE_SUBNET_EXCEPTION_ROLES`), with exact aliases and an SNI allowlist, forwarding to the shared proxy. | One proven path for development, CI and production, including split-horizon DNS and WireGuard meshes, with the guard intact for every other destination; the existing role-subnet exception mechanism already carries out-of-pool blocks, so no new SPOT is needed. |
| 5 | Keycloak SSO through native OIDC (`sso.flavor: oidc`); publishing permissions are enforced through OpenPost workspace roles. | OpenPost ships an OIDC adapter and does not consume group claims. |
| 6 | Shared `svc-db-postgres`; media on `web-app-seaweedfs` S3 when deployed, a role volume otherwise. | Postgres is the only multi-process database; S3 gives public media URLs for Meta. |
| 7 | One `all` process with one replica in compose and swarm. | State lives in Postgres and S3, so rescheduling is safe; split `web`/`worker` scaling is out of scope. |
| 8 | Provider app credentials live in the central `API` SPOT. | One place for proprietary credentials. |
| 9 | Diagnostics, update check, PostHog telemetry, feedback and public profiles are disabled. | No unnecessary transmission of internal data. |
| 10 | CI tests Fediverse publishing end to end against local instances through the relay, and the commercial adapters against a role-local provider simulator on the same role network; real platforms are checked manually in staging. | Real OAuth logins, public redirect hosts and per-post billing make real platforms unusable in CI. |
| 11 | Automated crossposting is a separate sidecar specified in [063](063-openpost-crossposter.md). | Separable deliverable and pull request. |

## Target Schema

### Role layout

```
roles/web-app-openpost/
├── Administration.md
├── README.md
├── files/
│   ├── playwright/
│   │   ├── _shared.js
│   │   ├── playwright.spec.js
│   │   └── test-*.js
│   ├── simulator/
│   └── test/
│       ├── probe.py
│       └── test.sh
├── meta/
│   ├── csp.yml
│   ├── domains.yml
│   ├── info.yml
│   ├── main.yml
│   ├── networks.yml
│   ├── rbac.yml
│   ├── secrets.yml
│   ├── services.yml
│   ├── tests.yml
│   ├── users.yml
│   ├── variants.yml
│   └── volumes.yml
├── tasks/
│   ├── 00_core.yml
│   ├── 01_fediverse_apps.yml
│   ├── 02_simulator.yml
│   ├── 03_breakglass.yml
│   └── main.yml
├── templates/
│   ├── compose.yml.j2
│   ├── env.j2
│   ├── playwright.env.j2
│   ├── relay.conf.j2
│   └── test.env.j2
└── vars/
    └── main.yml
```

`templates/relay.conf.j2` renders the relay's SNI map from the deployed sibling vhosts; `files/simulator/` holds the provider simulator mappings.

### `meta/services.yml` excerpt (proposed shape)

```yaml
openpost:
  image: ghcr.io/getopenpost/openpost
  version: "v7.22.9"
  update:
    type: registry_tags
  ports:
    internal:
      http: 8080
    local:
      http: 8100
  lifecycle: alpha
relay:
  image: nginx
  version: 1.31.7-alpine
simulator:
  enabled: false
  image: wiremock/wiremock
  version: "3.13.2"
```

## Acceptance Criteria

### Evaluation and documentation (story AC1)

- [x] `roles/web-app-openpost/Administration.md` documents, per network (Mastodon, Pixelfed, PeerTube, Facebook Pages, Instagram, X, YouTube, LinkedIn, Threads, TikTok, Bluesky), the supported post types, the developer app and account type, the required scopes, review or verification steps, quotas, costs and token upkeep.
- [x] `Administration.md` lists every unsupported feature with its workaround, including TikTok's ban on in-house upload tools, the X link surcharge, Instagram's JPEG and public-URL rule, LinkedIn vetting and Bluesky reach through `web-app-bridgy-fed`.
- [x] `Administration.md` documents data processing (which data each platform receives), third-party dependencies, and licence compatibility of the unmodified AGPL-3.0-only application with the role's own licence.
- [x] `Administration.md` contains a staging checklist and a verified-combinations matrix (network, content type, OpenPost version, date) for manual checks of the real platforms.

### Image and configuration (story AC2)

- [x] The role runs `ghcr.io/getopenpost/openpost` pinned to a release tag in `meta/services.yml` and ships no role-local Dockerfile or source modification.
- [x] The external update tooling proposes new upstream release tags through `update.type: registry_tags`.
- [x] Every OpenPost setting is rendered through `templates/env.j2`, and `OPENPOST_APP_URL` and `OPENPOST_PUBLIC_URL` carry `https://publish.{{ DOMAIN_PRIMARY }}`.

### Egress relay (story AC2, AC4, AC7)

- [ ] `roles/web-app-openpost/meta/networks.yml` declares the role subnet `192.88.99.0/24`, a block outside every range OpenPost's guard rejects and outside every Docker, mesh, Tor and role subnet pool, and `NETWORK_ROLE_SUBNET_EXCEPTION_ROLES` in `group_vars/all/08_networks.yml` names the role; the network is a bridge in compose and an overlay in swarm.
- [x] A `relay` entity running a pinned `nginx` image carries network aliases, passed through the `aliases` argument of the shared `container_networks` lookup, only for the canonical domains of the deployed sibling roles OpenPost publishes to (`web-app-mastodon`, `web-app-pixelfed`, `web-app-peertube`), each gated by that role's dynamic service flag.
- [ ] The relay forwards TLS unmodified by SNI to `host.docker.internal`, which `container_extra_hosts` resolves to the address that reaches the shared proxy in the effective deploy mode, and never resolves its own aliases.
- [x] The relay refuses every SNI that is not in its map.
- [x] When `TLS_MODE` is self-signed, OpenPost trusts the platform CA so that relayed vhosts verify; with public certificates no extra trust is configured.
- [x] The CLI test proves that OpenPost reaches an aliased sibling vhost, that it still rejects a private container name and a private IP literal, and that the relay refuses a TLS connection whose SNI is not in its map.
- [ ] Publishing to a local Mastodon account succeeds in swarm through the role's overlay network, verified by `make roundtrip apps="web-app-openpost"`.
- [x] `Administration.md` explains the guard, the relay, and how a deployment with sibling vhosts on another host or behind split-horizon DNS is covered.

### Deployment and operations (story AC2)

- [x] `publish.{{ DOMAIN_PRIMARY }}` serves the OpenPost UI through the shared OpenResty proxy with TLS and a `Content-Security-Policy` header, and `/api/v1/ready` returns HTTP 200.
- [ ] The role deploys green in compose (`make compose-deploy mode=reinstall apps=web-app-openpost full_cycle=true`) and in swarm, with one `all` replica and no reliance on `container_name`.
- [x] OpenPost stores its data in `svc-db-postgres`, and no SQLite database exists in the container.
- [x] With `web-app-seaweedfs` deployed, media lands in S3 and an uploaded file is fetchable anonymously over HTTPS from its public URL; without it, media lands in a role volume served under `/media/`.
- [x] Media URLs and `/api/v1/accounts/<provider>/callback` are reachable without a session, while every other UI and API route requires authentication.
- [x] The container healthcheck probes `/api/v1/health`, and the deploy waits for `/api/v1/ready`.
- [x] Database and media are part of the platform backup, and a restore drill (purge, restore, redeploy) brings back users, connected accounts and publications.
- [x] Changing the pinned version and redeploying migrates the schema without manual steps.
- [x] OpenPost sends mail through the platform mail service resolved by `lookup('email', application_id)`.

### Secrets and provider credentials (story AC2, AC7)

- [x] The JWT secret, encryption key and media signing key are generated through `meta/secrets.yml`, the OIDC client secret comes from `OIDC.CLIENT.SECRET`, and all of them reach OpenPost through the role's env file like every other role's secrets.
- [x] The break-glass instance admin `web-app-openpost-breakglass` is declared in `meta/users.yml` with a generated password, is bootstrapped as the first account on a fresh instance, and its e-mail differs from every Keycloak user so just-in-time provisioning never collides with it.
- [x] `group_vars/all/18_api.yml` gains the entries `x`, `meta`, `threads`, `linkedin`, `youtube` and `tiktok`, and the role renders them into `X_CLIENT_*`, `THREADS_CLIENT_*`, `LINKEDIN_CLIENT_*` and `OPENPOST_PROVIDER_APPS`.
- [x] A provider whose `lookup('api_enabled', ...)` is false cannot be connected in the UI.
- [x] Connected provider tokens are stored encrypted, verified by reading the token column from Postgres and finding no plaintext token.
- [x] `Administration.md` documents that OpenPost's X budget guardrail (`OPENPOST_X_MONTHLY_BUDGET_MICROUSD`) applies only in its cloud edition, so a self-hosted deployment caps X spending through the prepaid credits of the X developer account.

### Single sign-on (story AC3)

- [x] `meta/services.yml` declares `sso.flavor: oidc`, and OpenPost reads its issuer from `OIDC.CLIENT.ISSUER_URL`, its client from `OIDC.CLIENT.ID` and `OIDC.CLIENT.SECRET`, and uses the scopes `openid profile email`.
- [x] Password self-registration is closed and SSO users are provisioned just in time on their first login; because OpenPost gates both with `OPENPOST_DISABLE_REGISTRATIONS`, the role keeps the switch open when Keycloak is deployed and the shared proxy answers `POST /api/v1/auth/register` with HTTP 403.
- [x] The platform administrator becomes instance administrator through `OPENPOST_OIDC_BOOTSTRAP_ALLOWLIST` on first SSO login.
- [x] A just-in-time provisioned user without a workspace invitation cannot see or use the organisation workspace or its connected accounts.
- [x] `Administration.md` documents the break-glass procedure (`OPENPOST_SSO_BREAK_GLASS_EMAILS`), linking an existing account to its SSO identity, and the trusted-proxy fallback through oauth2-proxy.
- [x] `README.md` documents that OpenPost ships no LDAP adapter, so the role declares no `ldap` service and directory accounts sign in through Keycloak's OpenLDAP federation over OIDC.

### Telemetry and data minimisation (story AC7)

- [x] `OPENPOST_DIAGNOSTICS_ENABLED`, `OPENPOST_UPDATE_CHECK_ENABLED`, `OPENPOST_TELEMETRY_ENABLED`, `OPENPOST_FEEDBACK_ENABLED` and `OPENPOST_PUBLIC_PROFILES_ENABLED` are rendered as `false`, and the CLI test asserts it through the running instance.

### Fediverse publishing (story AC4)

- [x] The deploy registers an `OpenPost` app once on each deployed sibling Mastodon and Pixelfed instance, persists it, and pins it through `MASTODON_SERVERS` and `PIXELFED_SERVERS` named by the canonical URL, because the dynamic registration path of v7.22.9 fails its own readiness check on code exchange.
- [x] An administrator connects a local Mastodon account through the out-of-band code flow and publishes a text post that appears on the Mastodon instance.
- [x] An administrator connects a local Pixelfed account and publishes an image post that appears on the Pixelfed instance.
- [x] An administrator connects a local PeerTube account and publishes a video that appears on the PeerTube instance.

### Provider simulator (story AC4, AC8)

- [x] A `simulator` entity running the pinned `wiremock/wiremock` image is enabled by one `meta/variants.yml` variant only and is absent from the base configuration.
- [x] Inside that variant, the simulator joins the role network with aliases for the API hostnames OpenPost uses for X, Facebook, Instagram, YouTube, LinkedIn and TikTok, presents a certificate for those names signed by a per-deploy test CA, and OpenPost trusts that CA.
- [x] An X, Facebook Page, Instagram, YouTube, LinkedIn and TikTok account each connect through OpenPost's real callback against the simulator without a real provider login.
- [x] Publishing to those accounts produces the documented request sequence, asserted from the simulator's request journal: one X post within 280 weighted characters, one Facebook Page post, an Instagram media container followed by a publish call with a public JPEG URL, a resumable YouTube upload, one LinkedIn post, and one TikTok photo post followed by a status poll.
- [x] A simulated 429 response with a reset header is retried automatically and ends in exactly one successful delivery.
- [x] A simulated 503 response to a write leaves the destination in OpenPost's manual review instead of resending it, because OpenPost treats it as an ambiguous delivery; publishing the post again to that destination alone ends in exactly one successful delivery.
- [x] A permanent 4xx response leaves the rendition in a failed state that the UI shows together with the provider error, which OpenPost v7.22.9 reports as the provider's HTTP status and the reason `provider_rejected`.

### Publishing management (story AC6)

- [x] A post published immediately reaches the local Mastodon target, and a post scheduled two minutes ahead reaches its simulated destination exactly once and not before its time.
- [x] Every destination shows its state (scheduled, published, failed) and a failed destination can be retried alone.
- [x] Two accounts of the same network can be connected in one workspace and selected together for one publication.
- [x] A workspace member with a role that cannot publish is refused when publishing, while an editor succeeds.

### Variants, tests and quality (story AC8)

- [x] `meta/variants.yml` stays within the three-variant limit: variant 0 enables every integration but the onion, the simulator and the local Mastodon target, variant 1 adds the local Pixelfed and PeerTube targets with the integrations off, and variant 2 switches everything off, so no single round deploys all three instances; every variant deploys cleanly on a fresh host.
- [x] `files/playwright/` covers the `guest`, `biber` and `administrator` personas per the [Playwright contract](../contributing/artefact/files/role/playwright.specs.js.md), with the administrator connecting a Fediverse account and publishing, and `biber` being denied the organisation workspace.
- [x] `files/test/test.sh` with `templates/test.env.j2` covers readiness, the telemetry flags, the egress relay and its negative controls, token encryption at rest, Fediverse delivery and the simulator journal assertions.
- [ ] `make compose-playwright role=web-app-openpost` exits 0 without stub tests and ends logged out.
- [ ] `make roundtrip apps="web-app-openpost"` is green in compose and swarm.
- [ ] `make test` is green tree-wide.

### Role documentation

- [ ] `README.md` follows the [role README rules](../contributing/artefact/files/role/readme_md.md), including the Cosmos diagram with the relay, and states the image and bump policy, the egress relay, the SSO model and the telemetry defaults.
- [ ] This requirement is cross-linked from the implementing pull request and from the OpenProject work item.

## Validation Apps

```bash
INFINITO_PLAYWRIGHT_KEEP=true make compose-deploy mode=reinstall apps=web-app-openpost full_cycle=true
make roundtrip apps="web-app-openpost"
```

Smoke: open `https://publish.{{ DOMAIN_PRIMARY }}/`, sign in through Keycloak, connect the local Mastodon account, publish a post and find it on the Mastodon instance.

## Prerequisites

Before implementation, the agent MUST read [AGENTS.md](../../AGENTS.md), then [Compose Loop](../agents/action/iteration/compose.md), [Swarm Loop](../agents/action/iteration/swarm.md) and the [Playwright contract](../contributing/artefact/files/role/playwright.specs.js.md).

## Implementation Strategy

Execute autonomously and start from the proven egress topology: the role network on `192.88.99.0/24`, an nginx `stream` relay with `ssl_preread` and an SNI map, and OpenPost attached to that network.
Verify against the pinned upstream image before claiming a criterion: the provider hostnames and OAuth endpoints the simulator must answer, how OpenPost validates the OAuth `state` on its callback, and the account-linking flow.
Prove every relay and simulator change in the live stack via `make compose-exec` and `make compose-inner-run` before redeploying.

## Commit Policy

- No git commit until every Acceptance Criterion is checked off.
- When met and `make test` is green, instruct the operator to run `git-sign-push` outside the sandbox. The agent MUST NOT push.

## See Also

- Automated crossposting: [063-openpost-crossposter.md](063-openpost-crossposter.md)
- Requirement format: [requirements.md](../contributing/requirements.md)
- How agents process requirements: [requirements.md](../agents/action/requirements.md)
