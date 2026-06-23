# Changelog

## [10.1.0] - 2026-06-23

* New Pi-hole role (*web-app-pihole*) that ships the upstream Pi-hole DNS sinkhole and network-wide ad blocker, with its admin web interface gated behind *oauth2-proxy* and Keycloak RBAC and a native admin-password login (the *FTLCONF* web API password) available as a fallback variant. The upstream resolver and timezone are configurable, the role waits on the Pi-hole HTTP endpoint during deploy, and it is exercised end-to-end with Playwright covering the OAuth2, native-login and guest-access scenarios. The role ships at lifecycle beta.
* Routine maintenance: Docker image version bumps, a dependabot update of *globals* from 15.15.0 to 17.7.0, and minor *services.yml* self-provider flag corrections for ERPNext, GitLab, SeaweedFS and the Playwright end-to-end role.

**Contributors**

* [Prageeth Panicker](https://github.com/pragepani): Pi-hole role and its Playwright test suite
* [Kevin Veen-Birkenbach](https://veen.world): Pi-hole role hardening and review

## [10.0.1] - 2026-06-19

* Mark the *web-app-erpnext* role's own *erpnext* provider service with the *playwright-service-flag* self-provider suppression in *meta/services.yml*, fixing the Playwright service-flag integration guard that 10.0.0 tripped by exposing ERPNext as a consumable shared service.

**Contributors**

* [Kevin Veen-Birkenbach](https://veen.world): ERPNext self-provider test fix

## [10.0.0] - 2026-06-19

* New engine-agnostic object-store service (*web-app-seaweedfs*, backed by either *SeaweedFS* or *MinIO*) that exposes a shared S3 endpoint, now consumed across 14 web-app roles for media and asset storage. Nextcloud, Decidim, Shopware, PeerTube, Pixelfed, Taiga, Fider, Akaunting, Mobilizon and Matrix route their uploads to the central bucket, each exercised end-to-end with a SeaweedFS consumer check that requires a fresh object key per upload.
* Trusted-header single-sign-on bridges (wave 1) for *web-app-openproject*, *web-app-snipe-it*, *web-app-postmarks* and *web-app-yourls*, with *web-app-baserow* and *web-app-bookwyrm* migrating to the header bridge and dropping their LDAP configuration. The shared proxy (*sys-svc-proxy*) now strips forgeable identity headers on every location to close trusted-header injection.
* ERPNext is exposed as a consumable shared service and renders the Keycloak SSO button on */login* under gunicorn *--preload*. Nextcloud is provisioned on the SeaweedFS S3 object store with a dedicated consumer end-to-end test and has its OIDC plugins gated as mandatory; the upgrade to version 34 is deliberately not carried out because of plugin incompatibilities, so it stays pinned at 33.
* Extensive deploy and end-to-end hardening, much of it reproduced in Docker-in-Docker: native username and password login fallbacks for the no-SSO admin persona across Akaunting, Snipe-IT, YOURLS and OpenProject; OpenProject linked to the LDAP auth source for header SSO to fix a trusted-header 401, with all rails-runner Ruby extracted to dedicated files under *files/ruby/*; Shopware retries asset and theme builds against a restarting SeaweedFS; Mailu retries user creation and waits for antispam readiness before DKIM keygen; YOURLS creates its database schema on deploy; and OpenProject boots db:migrate under Ruby 4.0.
* Routine maintenance: Docker image and git-reference bumps, skills-lock refreshes, and dependabot updates (actions/checkout 6 to 7, @playwright/test 1.60.0 to 1.61.0, eslint 10.4.1 to 10.5.0).

**Contributors**

* [Kevin Veen-Birkenbach](https://veen.world): object-store service, trusted-header SSO bridges, role fixes and review

## [9.3.0] - 2026-06-11

* New Penpot role (web-app-penpot, requirement 235) that ships the upstream Penpot design platform comprising frontend, backend, exporter and Redis at image version 2.5.4, wired into the central Keycloak via OIDC and into the central OpenLDAP. Native local-password login is available as a toggle that is disabled automatically under OIDC, with the native-login and registration flags derived from the SSO flag. A custom JVM truststore imports the Infinito self-signed CA so OIDC over TLS succeeds, and the role is exercised end-to-end with Playwright covering OIDC login, logout and project creation. The local subnet was moved to 192.168.105.192/28 to avoid a collision with the ERPNext range.
* The Matrix role gains an ansible flavor (requirement 025) built on a unified compose template, with full Docker-in-Docker isolation, host-network mode cascaded to the addons and Jitsi, a central Postgres backend sharing the MATRIX_POSTGRES variables, and a central coturn aligned to the shared coturn variables for the MASH role. A dedicated MDAD runner image (python 3.13-slim with docker 28.0.4 CLI, migration validated against v2026.05.18.0) mounts the Infinito self-signed CA into both the runner and Synapse, and bootstrap now recovers cleanly from a stale marker.
* Smaller role fixes: ERPNext bypasses the v16 setup wizard per app and clears the Frappe cache after applying social-login, LDAP and email configuration; Friendica strips a trailing slash from the base URL and makes the admin-follow Playwright test idempotent; Funkwhale starts its API with gunicorn and binds the port.
* Routine maintenance: a lint that enforces a parameterised FROM in role Dockerfiles, a re-sync of the Claude settings allow-list with upstream, git references bumped to the latest semver tags (Bluesky 1.122.0 to 1.123.0, Bookwyrm v0.8.6 to v0.8.7), and Docker image version bumps across ERPNext v15.45.0 to v16.22.0, Friendica 2026.01 to 2026.05, Funkwhale 2.0.2 to 2.0.4, GitLab 19.0.1-ee.0 to 19.0.2-ee.0, Mattermost 11.7.2 to 11.8.0, OpenTalk v1.12.0 to v1.13.1, Prometheus v0.32.1 to v0.32.2, Shopware 3.6.0 to 3.7.0, MariaDB 12.2 to 12.3 and CoreDNS 1.14.3 to 1.14.4.

**Contributors**

* [Evangelos Tsakoudis](https://evangelostsak.com): Penpot role and its end-to-end test suite
* [Kevin Veen-Birkenbach](https://veen.world): Matrix ansible flavor, role fixes and review

## [9.2.0] - 2026-06-03

* New ERPNext role that ships the upstream Frappe Framework v15 stack as a web-app-erpnext role — backend, frontend, websocket, scheduler and two queue workers — wired into the central Keycloak via a built-in Keycloak Social Login Key and into the central OpenLDAP via the LDAP Settings doctype. The three-variant matrix (SSO plus LDAP, no auth, LDAP only) is exercised end-to-end and a repo-wide lint caps Ansible task names at 120 characters.
* New Jitsi Meet role that adds an oauth2-proxy gated meeting surface plus matching LDAP-variant Playwright coverage. The spec layout is reorganised into a shared module and per-scenario test files so future scenarios can be added without touching the monolith.
* Outbound mail and Nix install resilience: the dev-nix role guards its set_fact against getent returning None on hosts without an nixbld group, and the host-stack mail health checks keep behaving cleanly on minimal images.
* Routine maintenance: Docker image version bumps including Friendica 2026.01, eslint 10.4.0 to 10.4.1, and a dockerignore re-sync after the recent claude hooks addition.

**Contributors**

* Release maintained by Kevin Veen-Birkenbach, <https://veen.world>.

## [9.1.0] - 2026-06-01

* More robust Nix installer on Debian, Ubuntu, Fedora and CentOS systems: stale nixbld users from earlier installation attempts are cleaned up before the multi-user installer runs, and a long-standing crash on hosts where the nixbld group is absent has been resolved.
* Outbound mail health checks no longer fail silently on minimal container images: the heartbeat-email script copes with images that ship without the hostname binary, and the SSL trust file path is detected automatically across Red Hat, Debian, Ubuntu, Alpine and NixOS layouts.
* The Zammad helpdesk role completes its single-sign-on schema unification, with the variant matrix and Playwright test suite brought in line with the new shape.
* Internal infrastructure cleanups: re-synchronised .dockerignore and a shifted weekly CI schedule.

**Contributors**

* Release maintained by [Kevin Veen-Birkenbach](https://veen.world).

## [9.0.2] - 2026-05-29

* Restores the Debian dev-image build by introducing the INFINITO_VENV_DIR SPOT and calling infinito via its absolute venv path in scripts/docker/entry.sh, so the post-`make install` version check no longer trips on the PATH that bash -lc clobbers via /etc/profile; also scopes the auto-update PR dedup fingerprint to the files a run actually committed (instead of the whole commit tree) so unrelated drift on main no longer forces a fresh PR on every daily cron, nests web-app-bluesky's nocheck markers under the acl block they describe, and rolls up dependabot bumps (actions/cache 4→5, actions/setup-node 4→6) plus routine Docker image / git ref refreshes.

## [9.0.1] - 2026-05-28

* CI pipeline pass: PR flow now gates the env-matrix via a new detect-affected-roles resolver (skipped on role-only diffs); push CI skipped when an open PR exists (with 20s race retry for bot branches); pip cache + python 3.12 across all 16 workflows, plus npm and ansible-galaxy caches where missing. Update bot now deletes its own branches when closing superseded PRs.

## [9.0.0] - 2026-05-28

* Collapses the parallel **oauth2** and **oidc** top-level blocks in every role *meta/services.yml* into a single *services.sso* block with a **flavor** discriminator (*oidc* | *oauth2* | *saml*, default *oidc*). Flavor-specific keys live under *sso.<flavor>* (*sso.oauth2.{origin,acl,allowed_groups}*, *sso.oidc.plugin*).

**Removed**

* The dedicated oauth2-proxy provider role (its directory under *roles/*) is deleted; the 5 sidecar templates and the per-consumer render task fold into **web-app-keycloak** (*templates/sso_proxy/*, *tasks/sso_proxy.yml*). **web-app-keycloak** now declares **provides: sso**.
* The two mutual-exclusion guards (*tests/integration/iam/oauth2_oidc/test_mutual_exclusive.py*, *test_acl_mutual_exclusive.py*) — obsolete under the single-block schema.

**Added**

* *utils/roles/applications/services/sso.py* — central resolver for **is_enabled** / **is_proxy_gated** / **is_oidc_native** plus the oauth2 sub-values (*oauth2_origin_{host,port}*, *oauth2_acl*, *oauth2_allowed_groups*).
* Three lookup plugins on top of the resolver: **sso** (single-app predicate access), **sso_proxy_consumers** (enumerates oauth2-flavored consumers), **sso_oidc_plugin** (renamed from **oidc_flavor**, Nextcloud selector).
* *tests/lint/repository/no_legacy_sso_paths/* static guard against the legacy strings re-entering the source tree.

**Renamed**

* *services.<entity>.ports.local.oauth2* → *ports.local.sso*
* *PORT_BANDS.local.oauth2* → *PORT_BANDS.local.sso*
* **OAUTH2_PROXY_\*** env / Jinja vars → **SSO_PROXY_\***
* *oauth2_proxy_cookie_secret* → *sso_proxy_cookie_secret*
* **OAUTH2_SERVICE_ENABLED** + **OIDC_SERVICE_ENABLED** → single **SSO_SERVICE_ENABLED**
* Playwright gating helpers (*isServiceEnabled*, *skipUnlessServiceEnabled*, *requireService*, *safeIsEnabled*, *safeSkipUnlessEnabled*) move from service *oidc* / *oauth2* to *sso*
* *test_oauth2_contract.py* → *test_sso_contract.py*

**Changed**

* **sys-stk-backend**, **sys-svc-compose**, **sys-svc-proxy** and *plugins/filter/compose_volumes.py* now gate on **lookup(sso, …, is_proxy_gated)** instead of hand-combining **enabled** + **flavor**.
* Dual-block resolution: **web-app-bookwyrm** pinned to **flavor: oauth2**; **web-app-gitea** and **web-app-friendica** keep **flavor: oauth2** with the existing *oauth2.acl.blacklist* (*/user/login*) and *oauth2.acl.whitelist* (federation + discovery endpoints) — operative oauth2-proxy gating preserved.

**Migration**

Every consumer of the legacy oauth2 / oidc service sub-trees, the **OAUTH2_PROXY_\*** env / Jinja vars, **OAUTH2_SERVICE_ENABLED**, **OIDC_SERVICE_ENABLED**, *oauth2_proxy_cookie_secret*, *oauth2_proxy_application_id*, *ports.local.oauth2*, the dedicated oauth2-proxy provider role, or the legacy *oidc* / *oauth2* Playwright gating helper service names must migrate to the unified **sso** shape. Full plan and decisions are archived under req 21.

**Validated**

End-to-end against *web-app-{keycloak,nextcloud,bookwyrm,gitea,friendica,dashboard}* in matrix variants 0 and 1; v2 also passes Playwright for the four target roles (modulo a pre-existing **KC_HOSTNAME**-drift workaround, separate concern).

**Contributors**

* [Kevin Veen-Birkenbach](https://www.veen.world/)

## [8.0.5] - 2026-05-28

* Adds --version / -V flag to the infinito CLI, drops a dead Compose-CLI reference link, and fixes the dev-deploy router so per-invocation routing knobs (apps, mode, purge, bundles, disable, full_cycle, variant) no longer leak into the persistent .env and the make-alias / env-var surface is unified 1:1.

## Older Releases

* [008.000.004-2026-05-28.md](docs/changelog/008.000.004-2026-05-28.md)
* [008.000.003-2026-05-28.md](docs/changelog/008.000.003-2026-05-28.md)
* [008.000.002-2026-05-28.md](docs/changelog/008.000.002-2026-05-28.md)
* [008.000.001-2026-05-28.md](docs/changelog/008.000.001-2026-05-28.md)
* [008.000.000-2026-05-27.md](docs/changelog/008.000.000-2026-05-27.md)
* [007.000.000-2026-05-08.md](docs/changelog/007.000.000-2026-05-08.md)
* [006.000.000-2026-04-25.md](docs/changelog/006.000.000-2026-04-25.md)
* [005.002.000-2026-03-21.md](docs/changelog/005.002.000-2026-03-21.md)
* [005.001.000-2026-02-28.md](docs/changelog/005.001.000-2026-02-28.md)
* [005.000.000-2026-02-25.md](docs/changelog/005.000.000-2026-02-25.md)
* [004.001.000-2026-02-17.md](docs/changelog/004.001.000-2026-02-17.md)
* [004.000.003-2026-02-16.md](docs/changelog/004.000.003-2026-02-16.md)
* [004.000.002-2026-02-15.md](docs/changelog/004.000.002-2026-02-15.md)
* [004.000.001-2026-02-15.md](docs/changelog/004.000.001-2026-02-15.md)
* [004.000.000-2026-02-13.md](docs/changelog/004.000.000-2026-02-13.md)
* [003.000.000-2026-02-11.md](docs/changelog/003.000.000-2026-02-11.md)
* [002.001.009-2026-02-10.md](docs/changelog/002.001.009-2026-02-10.md)
* [002.001.008-2026-02-09.md](docs/changelog/002.001.008-2026-02-09.md)
* [002.001.007-2026-02-09.md](docs/changelog/002.001.007-2026-02-09.md)
* [002.001.006-2026-02-09.md](docs/changelog/002.001.006-2026-02-09.md)
* [002.001.005-2026-02-09.md](docs/changelog/002.001.005-2026-02-09.md)
* [002.001.004-2026-02-08.md](docs/changelog/002.001.004-2026-02-08.md)
* [002.001.003-2026-02-08.md](docs/changelog/002.001.003-2026-02-08.md)
* [002.001.002-2026-02-08.md](docs/changelog/002.001.002-2026-02-08.md)
* [002.001.001-2026-02-08.md](docs/changelog/002.001.001-2026-02-08.md)
* [002.001.000-2026-02-08.md](docs/changelog/002.001.000-2026-02-08.md)
* [002.000.000-2026-02-08.md](docs/changelog/002.000.000-2026-02-08.md)
* [001.000.000-2026-02-03.md](docs/changelog/001.000.000-2026-02-03.md)
* [000.012.000-2026-01-25.md](docs/changelog/000.012.000-2026-01-25.md)
* [000.011.000-2026-01-10.md](docs/changelog/000.011.000-2026-01-10.md)
* [000.010.000-2026-01-08.md](docs/changelog/000.010.000-2026-01-08.md)
* [000.009.000-2026-01-07.md](docs/changelog/000.009.000-2026-01-07.md)
* [000.008.000-2026-01-06.md](docs/changelog/000.008.000-2026-01-06.md)
* [000.007.002-2026-01-06.md](docs/changelog/000.007.002-2026-01-06.md)
* [000.007.001-2026-01-06.md](docs/changelog/000.007.001-2026-01-06.md)
* [000.007.000-2026-01-05.md](docs/changelog/000.007.000-2026-01-05.md)
* [000.006.000-2025-12-31.md](docs/changelog/000.006.000-2025-12-31.md)
* [000.005.000-2025-12-30.md](docs/changelog/000.005.000-2025-12-30.md)
* [000.004.000-2025-12-29.md](docs/changelog/000.004.000-2025-12-29.md)
* [000.003.005-2025-12-21.md](docs/changelog/000.003.005-2025-12-21.md)
* [000.003.004-2025-12-21.md](docs/changelog/000.003.004-2025-12-21.md)
* [000.003.003-2025-12-21.md](docs/changelog/000.003.003-2025-12-21.md)
* [000.003.002-2025-12-19.md](docs/changelog/000.003.002-2025-12-19.md)
* [000.003.001-2025-12-18.md](docs/changelog/000.003.001-2025-12-18.md)
* [000.003.000-2025-12-17.md](docs/changelog/000.003.000-2025-12-17.md)
* [000.002.001-2025-12-10.md](docs/changelog/000.002.001-2025-12-10.md)
* [000.002.000-2025-12-10.md](docs/changelog/000.002.000-2025-12-10.md)
* [000.001.001-2025-12-10.md](docs/changelog/000.001.001-2025-12-10.md)
* [000.001.000-2025-12-09.md](docs/changelog/000.001.000-2025-12-09.md)
