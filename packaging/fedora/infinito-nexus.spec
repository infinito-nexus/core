Name:           infinito-nexus
Version:        11.0.0
Release:        1%{?dist}
Summary:        Meta package for Infinito.Nexus host dependencies

License:        LicenseRef-Infinito-Nexus-Community-License
URL:            https://github.com/kevinveenbirkenbach/infinito-nexus
BuildArch:      noarch

Requires:       ansible-core
Requires:       bash
Requires:       ca-certificates
Requires:       curl
Requires:       dbus
Requires:       (docker-ce-cli or docker or moby-engine)
Requires:       docker-compose-plugin
Requires:       gettext
Requires:       git
Requires:       jq
Requires:       make
Requires:       openssh-clients
#
# EL9 AppStream exposes only python3.9 via the generic python3 capability.
# In those environments we still bootstrap Python 3.11+ separately via
# roles/dev-python/files/install.sh, but the RPM metadata must remain
# installable from the stock distro repositories.
%if 0%{?rhel} == 9
Requires:       python3
%else
Requires:       python3 >= 3.11
%endif
Requires:       python3-pip
Requires:       python3-pyyaml
Requires:       rsync
Requires:       sudo
Requires:       systemd
Requires:       tar
Recommends:     bind-utils
Recommends:     shellcheck
Recommends:     shfmt

%description
This package installs the OS-level dependencies required by Infinito.Nexus
development and CI workflows (make, Python, Docker CLI, Ansible controller
tooling, and helper utilities). It intentionally ships no application binaries.

%prep
:

%build
:

%install
install -d %{buildroot}%{_docdir}/%{name}
: > %{buildroot}%{_docdir}/%{name}/DEPENDENCIES

%files
%doc %{_docdir}/%{name}/DEPENDENCIES

%changelog
* Sat Jun 27 2026 Kevin Veen-Birkenbach <kevin@veen.world> - 11.0.0-1
- Unified addon syntax (requirement 026): every role-level plugin, browser/GNOME extension, Matrix bridge and cross-role integration was migrated to a single declarative *meta/addons/* contract, replacing the per-role ad-hoc plugin definitions. 86 addon files now describe addons for *desk-chromium*, *desk-firefox*, *desk-gnome*, *web-app-discourse*, *web-app-friendica*, *web-app-joomla*, *web-app-mediawiki*, *web-app-pretix*, *web-app-wordpress*, *web-app-xwiki*, *web-app-nextcloud*, *web-app-odoo* and *web-app-matrix*. Each service-coupled addon gets a *tasks/addons* integration hook and its own Playwright spec (87 per-addon specs added), addon flags are gated on actual partner deployment through a new *addon_env_flags* lookup, and a lint requires a hook plus a spec for every coupled addon. The cross-role integration matrix is regenerated from a dedicated data module (*integration_matrix_data.py*).
* New centralized API single-point-of-truth: an *api* lookup plugin plus a global API dict so API tokens and endpoints (Cloudflare, the Nextcloud proprietary OAuth integrations) resolve from one place instead of scattered role lookups.
* Real Nextcloud integration coupling: end-to-end tests now assert genuine two-way OAuth/API coupling for *gitlab*, *mattermost*, *openproject*, *zammad*, *peertube*, *discourse*, *github*, *google*, *jira*, *mastodon*, *matrix*, *moodle* and *suitecrm*, rather than the mere presence of a connect button. All integration OAuth credentials are stored Nextcloud-encrypted via ICrypto (sensitive app values), OpenProject and Zammad secrets survive a re-deploy, and OpenWebUI/Ollama is wired in as a real *integration_openai* chat backend. Bridges with no Nextcloud-33 plugin (Moodle, SuiteCRM) are disabled.
* Nextcloud deploy-variant rebalancing: Discourse and OnlyOffice are each isolated into their own loosely-coupled partner variant, the matrix is repacked to five variants overriding only the dynamic flags, LDAP is enabled wherever SSO is on, and the database is shared outside variant 1. The GitLab 19 OAuth app now carries an organization, and *fileslibreofficeedit* is gated on OnlyOffice absence.
* Storage- and runtime-aware CI variant matrix: variant bundles are split per runner by a storage-aware job splitter driven by an explicit variant CSV, behind a unified variant selector (*variant_select.py*). The default per-bundle storage cap is centralized at 350GB, per-variant memory budgets are guarded against the host budget, shared database providers are enforced by a shared-false-once lint, and the full variant matrix always runs (the earlier runtime time-cut was removed).
* Container resource governance: self-run and shared-provider services declare explicit compose mem/pids limits, container limits were right-sized across roles, and Node-heap services respect a floor via a new *node_max_old_space_size* lookup (Nextcloud whiteboard raised to 1g). A reworked *ressources* CLI emits per-variant and all-role resource summaries, the footprint tool gains a *min_storage* column, and shared services carry a *bond* integration-importance factor.
* Matrix bridges modernized: Signal, Telegram, WhatsApp and Slack bridges migrate to bridgev2 config, the dead mautrix-facebook/instagram bridges are replaced by mautrix-meta, bridge specs are gated by the deployed addon, Synapse loads the bridge registrations from a mounted directory, and the role now tracks *matrix-docker-ansible-deploy* from the spantaleev upstream.
* CA-trust and OIDC-over-self-signed-TLS hardening: the internal CA is installed into the OS bundle for PHP libcurl OIDC (*web-app-pixelfed*, *web-app-joomla*, plus a WordPress must-use plugin), the CA-trust wrapper is kept on probe timeout instead of degrading to env-only, and the CA injection is bounded so it cannot hang the handler. HSTS is now emitted on every response including non-2xx, *ansible-vault encrypt_string* reads plaintext from stdin so leading-dash values encrypt, and Mastodon allows inline *script-src-elem* for its server-rendered SPA.
* Image and dependency version jumps (net since 10.1.1):
  * *web-app-erpnext*: v16.23.1 to v16.25.0
  * *web-app-gitlab*: 19.1.0-ee.0 to 19.1.1-ee.0
  * *web-app-opencloud*: 4.0.7 to 7.2.0
  * *web-app-seaweedfs*: 4.35 to 4.36
  * *web-app-matomo*: unpinned *latest* to pinned 5.3.2 (matches the bootstrap installer)
  * *web-app-nextcloud* proxy (nginx): unpinned *alpine* to pinned 1.31.2-alpine
  * *web-app-nextcloud* whiteboard: unpinned *latest* to pinned v1.5.9
  * *svc-ai-ollama*: switched to the official *ollama* image so inference works
  * *web-app-pretix* and *web-app-xwiki*: their inline plugin/extension version pins (2.3.1; 2.19.6, 9.15.7, 1.0) were removed as those addons moved into *meta/addons*
  * Dev/CI dependencies: *globals* 15.15.0 to 17.7.0, *@playwright/test* 1.61.0 to 1.61.1, *actions/cache* 5 to 6
  * Intermediate bot bumps were corrected back down: Mattermost 11.8.2 to 11.8.1 and Nextcloud 34 to 33 (kept at 33 because of plugin incompatibilities, same pin as 10.0.0)

Contributors
* [Kevin Veen-Birkenbach](https://veen.world): unified addon syntax, API single-point-of-truth, Nextcloud integrations and variant rebalancing, CI variant bundling, resource governance, Matrix bridge migration and version maintenance

* Thu Jun 11 2026 Kevin Veen-Birkenbach <kevin@veen.world> - 9.3.0-1
- * New Penpot role (web-app-penpot, requirement 235) that ships the upstream Penpot design platform comprising frontend, backend, exporter and Redis at image version 2.5.4, wired into the central Keycloak via OIDC and into the central OpenLDAP. Native local-password login is available as a toggle that is disabled automatically under OIDC, with the native-login and registration flags derived from the SSO flag. A custom JVM truststore imports the Infinito self-signed CA so OIDC over TLS succeeds, and the role is exercised end-to-end with Playwright covering OIDC login, logout and project creation. The local subnet was moved to 192.168.105.192/28 to avoid a collision with the ERPNext range.
* The Matrix role gains an ansible flavor (requirement 025) built on a unified compose template, with full Docker-in-Docker isolation, host-network mode cascaded to the addons and Jitsi, a central Postgres backend sharing the MATRIX_POSTGRES variables, and a central coturn aligned to the shared coturn variables for the MASH role. A dedicated MDAD runner image (python 3.13-slim with docker 28.0.4 CLI, migration validated against v2026.05.18.0) mounts the Infinito self-signed CA into both the runner and Synapse, and bootstrap now recovers cleanly from a stale marker.
* Smaller role fixes: ERPNext bypasses the v16 setup wizard per app and clears the Frappe cache after applying social-login, LDAP and email configuration; Friendica strips a trailing slash from the base URL and makes the admin-follow Playwright test idempotent; Funkwhale starts its API with gunicorn and binds the port.
* Routine maintenance: a lint that enforces a parameterised FROM in role Dockerfiles, a re-sync of the Claude settings allow-list with upstream, git references bumped to the latest semver tags (Bluesky 1.122.0 to 1.123.0, Bookwyrm v0.8.6 to v0.8.7), and Docker image version bumps across ERPNext v15.45.0 to v16.22.0, Friendica 2026.01 to 2026.05, Funkwhale 2.0.2 to 2.0.4, GitLab 19.0.1-ee.0 to 19.0.2-ee.0, Mattermost 11.7.2 to 11.8.0, OpenTalk v1.12.0 to v1.13.1, Prometheus v0.32.1 to v0.32.2, Shopware 3.6.0 to 3.7.0, MariaDB 12.2 to 12.3 and CoreDNS 1.14.3 to 1.14.4.

**Contributors**

* [Evangelos Tsakoudis](https://evangelostsak.com): Penpot role and its end-to-end test suite
* [Kevin Veen-Birkenbach](https://veen.world): Matrix ansible flavor, role fixes and review

* Wed Jun 03 2026 Kevin Veen-Birkenbach <kevin@veen.world> - 9.2.0-1
- * New ERPNext role that ships the upstream Frappe Framework v15 stack as a web-app-erpnext role — backend, frontend, websocket, scheduler and two queue workers — wired into the central Keycloak via a built-in Keycloak Social Login Key and into the central OpenLDAP via the LDAP Settings doctype. The three-variant matrix (SSO plus LDAP, no auth, LDAP only) is exercised end-to-end and a repo-wide lint caps Ansible task names at 120 characters.
* New Jitsi Meet role that adds an oauth2-proxy gated meeting surface plus matching LDAP-variant Playwright coverage. The spec layout is reorganised into a shared module and per-scenario test files so future scenarios can be added without touching the monolith.
* Outbound mail and Nix install resilience: the dev-nix role guards its set_fact against getent returning None on hosts without an nixbld group, and the host-stack mail health checks keep behaving cleanly on minimal images.
* Routine maintenance: Docker image version bumps including Friendica 2026.01, eslint 10.4.0 to 10.4.1, and a dockerignore re-sync after the recent claude hooks addition.

Release maintained by Kevin Veen-Birkenbach, <https://veen.world>.

* Mon Jun 01 2026 Kevin Veen-Birkenbach <kevin@veen.world> - 9.1.0-1
- * * More robust Nix installer on Debian, Ubuntu, Fedora and CentOS systems: stale nixbld users from earlier installation attempts are cleaned up before the multi-user installer runs, and a long-standing crash on hosts where the nixbld group is absent has been resolved.
* Outbound mail health checks no longer fail silently on minimal container images: the heartbeat-email script copes with images that ship without the hostname binary, and the SSL trust file path is detected automatically across Red Hat, Debian, Ubuntu, Alpine and NixOS layouts.
* The Zammad helpdesk role completes its single-sign-on schema unification, with the variant matrix and Playwright test suite brought in line with the new shape.
* Internal infrastructure cleanups: re-synchronised .dockerignore and a shifted weekly CI schedule.

Release maintained by [Kevin Veen-Birkenbach](https://veen.world).

* Fri May 29 2026 Kevin Veen-Birkenbach <kevin@veen.world> - 9.0.2-1
- * Restores the Debian dev-image build by introducing the INFINITO_VENV_DIR SPOT and calling infinito via its absolute venv path in scripts/docker/entry.sh, so the post-`make install` version check no longer trips on the PATH that bash -lc clobbers via /etc/profile; also scopes the auto-update PR dedup fingerprint to the files a run actually committed (instead of the whole commit tree) so unrelated drift on main no longer forces a fresh PR on every daily cron, nests web-app-bluesky's nocheck markers under the acl block they describe, and rolls up dependabot bumps (actions/cache 4→5, actions/setup-node 4→6) plus routine Docker image / git ref refreshes.

* Thu May 28 2026 Kevin Veen-Birkenbach <kevin@veen.world> - 9.0.1-1
- * CI pipeline pass: PR flow now gates the env-matrix via a new detect-affected-roles resolver (skipped on role-only diffs); push CI skipped when an open PR exists (with 20s race retry for bot branches); pip cache + python 3.12 across all 16 workflows, plus npm and ansible-galaxy caches where missing. Update bot now deletes its own branches when closing superseded PRs.

* Thu May 28 2026 Kevin Veen-Birkenbach <kevin@veen.world> - 9.0.0-1
- * Collapses the parallel **oauth2** and **oidc** top-level blocks in every role *meta/services.yml* into a single *services.sso* block with a **flavor** discriminator (*oidc* | *oauth2* | *saml*, default *oidc*). Flavor-specific keys live under *sso.<flavor>* (*sso.oauth2.{origin,acl,allowed_groups}*, *sso.oidc.plugin*).

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

* Thu May 28 2026 Kevin Veen-Birkenbach <kevin@veen.world> - 8.0.5-1
- * Adds --version / -V flag to the infinito CLI, drops a dead Compose-CLI reference link, and fixes the dev-deploy router so per-invocation routing knobs (apps, mode, purge, bundles, disable, full_cycle, variant) no longer leak into the persistent .env and the make-alias / env-var surface is unified 1:1.

For older releases, see https://docs.infinito.nexus/

Earlier releases:
  8.0.4 (2026-05-28)
  8.0.3 (2026-05-28)
  8.0.2 (2026-05-28)
  8.0.1 (2026-05-28)
  8.0.0 (2026-05-27)
  7.0.0 (2026-05-08)
  6.0.0 (2026-04-25)
  5.2.0 (2026-03-21)
  5.1.0 (2026-02-28)
  5.0.0 (2026-02-25)
  4.1.0 (2026-02-17)
  4.0.3 (2026-02-16)
  4.0.2 (2026-02-15)
  4.0.1 (2026-02-15)
  4.0.0 (2026-02-13)
  3.0.0 (2026-02-11)
  2.1.9 (2026-02-10)
  2.1.8 (2026-02-09)
  2.1.7 (2026-02-09)
  2.1.6 (2026-02-09)
  2.1.5 (2026-02-09)
  2.1.4 (2026-02-08)
  2.1.3 (2026-02-08)
  2.1.2 (2026-02-08)
  2.1.1 (2026-02-08)
  2.1.0 (2026-02-08)
  2.0.0 (2026-02-08)
  1.0.0 (2026-02-03)
  0.12.0 (2026-01-25)
  0.11.0 (2026-01-10)
  0.10.0 (2026-01-08)
  0.9.0 (2026-01-07)
  0.8.0 (2026-01-06)
  0.7.2 (2026-01-06)
  0.7.1 (2026-01-06)
  0.7.0 (2026-01-05)
  0.6.0 (2025-12-31)
  0.5.0 (2025-12-30)
  0.4.0 (2025-12-29)
  0.3.5 (2025-12-21)
  0.3.4 (2025-12-21)
  0.3.3 (2025-12-21)
  0.3.2 (2025-12-19)
  0.3.1 (2025-12-18)
  0.3.0 (2025-12-17)
  0.2.1 (2025-12-10)
  0.2.0 (2025-12-10)
  0.1.1 (2025-12-10)
  0.1.0 (2025-12-09)
