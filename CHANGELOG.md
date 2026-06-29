# Changelog

## [11.3.0] - 2026-06-29

* Security: resolve all 80 open CodeQL/code-scanning alerts on the branch and add guards so they cannot recur. The security-sensitive fixes break an unsafe import cycle in the *cli/administration/deploy/development* package by extracting the env/arg helpers into a leaf *env.py* (load-time DAG *compose → common → deps → env*); harden the *web-app-bluesky* login-broker (*server.js*) with a prototype-pollution guard on cookie parsing, CR/LF + control-char log sanitisation, HTML-escaped exception text and a ReDoS-bounded handle regex; harden the *web-app-baserow* SSO open-redirect *next* handling; require TLS ≥ 1.2 in the network diagnose probes; validate *actionlint* installer tar members against path traversal; rewrite the *decidim*/*apt-purge* lint regexes to avoid catastrophic backtracking; and anchor six Playwright URL regexes while pinning *crs-k/stale-branches* to a commit SHA. Recurrence guards: an *import-linter* contract (wired into *pyproject* and *tests/lint*) now fails CI on a new dev-deploy cycle instead of relying on CodeQL, a new lint requires every bandit *S###* *noqa* to carry a justification, and *BLE001* (blind-except) is added to ruff as a ratchet (tests/roles exempt, current production offenders grandfathered). Intentional false positives (Django settings patches, the Odoo `__manifest__`, side-effect and cross-module imports) are left in place.

* CI flakiness and fork-PR fixes: the Odoo *sale_management* Playwright spec adds *.first()* so the success case no longer trips a strict-mode violation when both the menu brand and the breadcrumb render; the Nextcloud GitLab-OAuth provisioning now resolves/creates the default Organization defensively with *retries/until* instead of hard-raising during the async seed window; the Jenkins deploy-lockdown service stop and the Moodle shared *compose up* handler each gain *retries/until* to ride out transient systemd "Transaction is destructive" contention and a not-yet-created external network. The fork image mirror gets *secrets: inherit* restored (follow-up to the 11.2.0 credential hardening) so untrusted fork PRs authenticate to Docker Hub again rather than mirroring anonymously and hitting rate limits — the build keeps its hardening since it pulls its parent from GHCR. The stale-branches cleanup is adjusted for *crs-k/stale-branches@v9.0.1*, which rejects *days-before-stale ≥ days-before-delete*: stale is now 350 days and delete 360 (10-day warning before deletion at 360 days of inactivity). See [the fork-PR pipeline](docs/contributing/artefact/git/pipeline.md) and [the workflow catalog](docs/contributing/tools/github/actions/workflows.md).

* Routine maintenance: *.gitignore* now excludes local Claude agent artefacts (*launch.json*, *routines*, *workflows*), and dependabot bumps of *actions/stale* 9 → 10 and *eslint* 10.5.0 → 10.6.0.

* Image and dependency version jumps (net since 11.2.0):
  * *web-app-seaweedfs*: 4.36 to 4.37
  * *pkgmgr* (package-manager git ref): v1.15.2 to v1.16.0

**Contributors**

* [Kevin Veen-Birkenbach](https://veen.world): code-scanning alert resolution and recurrence guards, CI/fork-PR fixes and version maintenance

## [11.2.0] - 2026-06-28

* Per-role update PRs: the Docker-image-version and repository-ref updaters now open one pull request per affected role instead of a single combined PR, and they recompute the diff against the latest *main* at run time — the update jobs check out *main* rather than the triggering commit, so a queued or stale run no longer proposes already-merged changes or bundles unrelated roles. Each role gets its own branch (*update/<type>-<role>-<date>-<fingerprint>*) and a role-scoped duplicate check, while the *skills-lock.json* updater deliberately stays a single PR. See [the update workflow catalog](docs/contributing/tools/github/actions/workflows.md).

* Fork-PR CI hardening (follow-up to the 11.1.0 trusted-fork flow): the privileged *pull_request_target* image producer and mirror now set *allow-unsafe-pr-checkout* so *actions/checkout* stops refusing the merged fork ref it had begun rejecting. Untrusted fork builds run without organization secrets — they authenticate to GHCR with the per-job *GITHUB_TOKEN* only and mirror Docker Hub anonymously — while the maintainer-trusted path keeps full credentials and builds the raw PR head. The trust switch moved to the *🛡️ Trusted* label. See [the fork-PR pipeline](docs/contributing/artefact/git/pipeline.md) and [the GHCR authentication reference](docs/contributing/tools/ghcr/authentication.md).

* Buildx setup resilience: the CI image build pre-pulls and pins the *moby/buildkit* image with a retry loop before *docker/setup-buildx-action*, so a transient *registry-1.docker.io* timeout during the buildkit bootstrap no longer aborts the build — buildx falls back to the locally cached image once it is present.

* Cleanup-workflow fixes (follow-up to the 11.1.0 cleanup automation): the *crs-k/stale-branches* action is pinned to *v9.0.1* (the previous *@v8* was unresolvable and failed the job) and its non-existent *protected-branches* input is replaced with the action's real *branches-filter-regex*; the GHCR CI-image cleanup script now reports what it scans, keeps and deletes with a per-package summary and a *DRY_RUN* mode, so a no-op run is no longer indistinguishable from a broken one.

* Routine maintenance: YAML normalization of the *web-app-pihole* role's *meta/services.yml* (document start, list indentation) and an autoformat pass.

* Image and dependency version jumps (net since 11.1.0):
  * *web-app-matomo*: 5.3.2 to 5.11.2
  * *web-app-mattermost*: 11.8.1 to 11.8.2
  * *web-app-opentalk* (LiveKit): v1.13.1 to v1.13.2

**Contributors**

* [Kevin Veen-Birkenbach](https://veen.world): per-role update PRs, fork-PR CI hardening, buildx retry, cleanup-workflow fixes and version maintenance

## [11.1.0] - 2026-06-27

* Trusted fork PRs: a maintainer-applied *trusted-pr* label runs a fork PR as deliberately released code — the orchestrator skips the fork-prerequisite wait and the privileged *pull_request_target* build switches its source from the base merge ref to the raw PR head, while the built image keeps the merge-SHA tag so every downstream consumer is unchanged. The label is the only switch (applying a label is collaborator-only on GitHub, so fork authors cannot grant it), build-orchestration scripts always come from the base repository, and both unlabeled fork PRs and same-repository PRs are untouched. See [the fork-PR pipeline](docs/contributing/artefact/git/pipeline.md) and [the contributor fork workflow](docs/contributing/artefact/git/pull-request.md).

* Fork main-branch sync: the push entry workflow now synchronizes the current repository's *main* from a configured source repository (default *infinito-nexus/core*) before CI scope and deploy discovery run, so a fork branch push sees only its own changes against an up-to-date base. The source is overridable or disablable through the *CI_SYNC_MAIN_SOURCE_REPOSITORY* repository variable, and the sync force-overwrites *main*, so a synced repository must not be used as a working branch. See [the Actions configuration reference](docs/contributing/tools/github/actions/configuration.md).

* Package-changelog generator hardening: the Debian changelog and the Fedora spec *%changelog* are mirrored from CHANGELOG.md without tripping their native parsers — every change line is indented for Debian, every body line gains a dash continuation for RPM, and the archived-releases notice is folded into the oldest kept entry instead of trailing after the final entry. Previously the un-indented bodies made *dpkg-buildpackage* abort the Debian package build with an empty maintainer. The *Changelog* title is also preserved when the active window is trimmed. See [the release procedure](docs/contributing/actions/release.md).

* New packaging lint: a *lint-packages* check, wired into *make lint* and its own CI workflow, validates the generated *debian/changelog* with *dpkg-parsechangelog*, the Fedora spec with *rpmspec* and the Arch *PKGBUILD* with a *bash -n* syntax pass, failing on any parser warning rather than only on a non-zero exit. A complementary *test-lint* check asserts that both package changelogs list every released version and that their inline window matches CHANGELOG.md. See [the workflow catalog](docs/contributing/tools/github/actions/workflows.md).

* Repository cleanup automation: a scheduled cleanup workflow plus a GHCR helper prune stale CI images so the container registry does not accumulate per-commit build artefacts.

* Routine maintenance: YAML normalization of the *web-app-pihole* role variables (document start, single-space keys).

**Contributors**

* [Kevin Veen-Birkenbach](https://veen.world): trusted-fork-PR flow, fork main sync, package-changelog generator and packaging lint, cleanup automation

## [11.0.0] - 2026-06-27

* Unified addon syntax (requirement 026): every role-level plugin, browser/GNOME extension, Matrix bridge and cross-role integration was migrated to a single declarative *meta/addons/* contract, replacing the per-role ad-hoc plugin definitions. 86 addon files now describe addons for *desk-chromium*, *desk-firefox*, *desk-gnome*, *web-app-discourse*, *web-app-friendica*, *web-app-joomla*, *web-app-mediawiki*, *web-app-pretix*, *web-app-wordpress*, *web-app-xwiki*, *web-app-nextcloud*, *web-app-odoo* and *web-app-matrix*. Each service-coupled addon gets a *tasks/addons* integration hook and its own Playwright spec (87 per-addon specs added), addon flags are gated on actual partner deployment through a new *addon_env_flags* lookup, and a lint requires a hook plus a spec for every coupled addon. The cross-role integration matrix is regenerated from a dedicated data module (*integration_matrix_data.py*).
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

**Contributors**

* [Kevin Veen-Birkenbach](https://veen.world): unified addon syntax, API single-point-of-truth, Nextcloud integrations and variant rebalancing, CI variant bundling, resource governance, Matrix bridge migration and version maintenance

## [10.1.1] - 2026-06-24

* Disabled the *email* service in the *web-app-pihole* role by pinning *services.email* to a static *enabled: false* / *shared: false* with the matching *dynamic-flag* and *email* nocheck suppressions, removing the now-static email overrides from *meta/variants.yml*, and adding *javascript* true/false variant pins to keep the dynamic-flag matrix-coverage guard green.

**Contributors**

* [Kevin Veen-Birkenbach](https://veen.world): Pi-hole email service disablement

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
