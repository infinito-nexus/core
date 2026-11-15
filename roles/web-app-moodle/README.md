# Moodle

## Description

Ignite the learning experience with [Moodle](https://moodle.org/), a powerful and versatile platform for online education that energizes classrooms and fosters interactive learning. Moodle delivers a comprehensive set of tools for creating, managing, and sharing educational content, supporting collaboration among educators and learners alike.

## Overview

This role deploys Moodle using Docker, automating the setup of both the Moodle application and its underlying MariaDB database. It integrates with an NGINX reverse proxy to ensure secure and efficient web access and uses persistent storage to safeguard your data and configuration.

## Features

- **Comprehensive e-Learning Platform:** Offers an extensive array of features including course management, assessment tools, and collaborative resources.
- **Customizable Interface:** Tailor the look and feel of your learning environment with numerous themes and plugins.
- **Scalable Deployment:** Leverage Docker for a portable and scalable installation that adapts as your user base grows.
- **Robust Data Management:** Secure and reliable storage of both the Moodle application and user data through Docker volumes.
- **Secure Web Access:** Configured to work seamlessly behind an NGINX reverse proxy for enhanced security and performance.
- **Single Sign-On (SSO) / OpenID Connect (OIDC):** Seamless integration with external identity providers for centralized authentication.
- **Login methods:** `services.moodle.login.method` declares `sso`, `ldap`, `native`, `2fa` and `registration`, and [`tasks/05_login_methods.yml`](./tasks/05_login_methods.yml) converges them on every deploy. `sso` puts `oidc` into Moodle's `auth` list and, while `native` is off, points `alternateloginurl` at `auth/oidc/`, so `/login/index.php` hands every visitor to Keycloak. `ldap` puts `ldap` into the `auth` list; under SSO `auth_ldap` stays in the list as a directory sync source only, behind the redirect. `native` is Moodle's always-enabled manual auth, served by the same form as LDAP accounts (shared form); with SSO it only decides whether `alternateloginurl` hides that form, and in LDAP mode the only manual account is the site administrator. `2fa` sets `tool_mfa/enabled` and `factor_totp/enabled`. While it is on, `login.method.2fa.enforced: true`, the role default, turns `factor_nosetup` off, `factor_grace` on with `forcesetup`, and [`local_mfaenforce`](./files/build/local/mfaenforce/classes/observer.php) on, a plugin the image carries and the deploy syncs into the code volume: it starts the grace period of every sign-in as already expired, so an account without a factor, the administrator included, is sent to setup at its first sign-in and gets in once it has enrolled one; `enforced: false` keeps `factor_nosetup` on and switches `local_mfaenforce` off, so accounts may enrol a TOTP factor while accounts without one pass. [`files/php/provision/mfa_grace.php`](./files/php/provision/mfa_grace.php) records a `factor_grace` the deploy switched on in `local_mfaenforce/grace_by_deploy`, and `enforced: false` switches only that one off again; a `factor_grace` an admin switched on stays. Every variant in [`meta/variants.yml`](./meta/variants.yml) with SSO off sets `enforced: false`, so its automated logins skip enrollment. While `2fa` is off the deploy turns `tool_mfa` off, which leaves no factor to enforce, and switches `factor_grace` off, also one an admin set, so a returning `2fa` starts without a dormant enforcement. Enforcing does not cut off the MCP server on the pinned Moodle 5.3.0: a token request is not logged in when `tool_mfa_after_config` runs, and `external_api::validate_context` calls `require_login` with `preventredirect`, for which `\tool_mfa\manager::should_require_mfa` returns `NO_REDIRECT` before its web-service branch. `registration` sets `registerauth=email` and adds `email` to the `auth` list. **Break-glass:** `/login/index.php?loginredirect=0` keeps the form reachable under SSO, but `tasks/04_oidc.yml` moves every account to `auth_oidc`, so the administrator regains form access only through Moodle's CLI in the container (`admin/cli/cfg.php`, `admin/cli/reset_password.php` after switching its `auth` back to `manual`).
- **Managed settings:** [`meta/forms.yml`](./meta/forms.yml) declares the `auth_oidc` settings (application, binding claim, sign-out, display and field mapping pages) and the `auth_ldap` settings (connection, role mapping and field mapping) every deploy writes, with their values in `services.moodle.auth_oidc` and `services.moodle.auth_ldap` of [`meta/services.yml`](./meta/services.yml). Moodle locks them itself: `MOODLE_FORCED_PLUGIN_SETTINGS` carries both plugins' settings into `.env/env`, and [`files/build/config.php`](./files/build/config.php) merges them into `$CFG->forced_plugin_settings`, so the admin pages show every managed setting as defined in config.php and no admin save can change it. [`tasks/utils/plugin/form.yml`](./tasks/utils/plugin/form.yml) still reads the stored `config_plugins` rows through [`files/php/provision/plugin_config.php`](./files/php/provision/plugin_config.php) first, the deploy log and the journal report each row that differs from the forced value, and the write aligns only those rows, so lifting the force keeps the managed values. The OIDC scopes and `removecontexts` have no form field but are forced the same way: the scopes come from the `moodle` client scope of web-app-keycloak, and `removecontexts` has no field on the page. The client secret and the bind password stay out of the environment and unforced: the applier receives them on stdin, compares and writes them, and never prints them. `plugin_config.php` refuses a setting that config.php forces to another value.
- **Profile Sync:** `auth_oidc` and `auth_ldap` overwrite the mapped profile fields on every login, and the profile form shows them read-only. The claim names come from `OIDC.ATTRIBUTES` and the attribute names from `LDAP.USER.ATTRIBUTES`. The address, city and country read the flat `street`, `locality` and `country` claims of the `moodle` client scope of web-app-keycloak.
- **Role Mapping:** Members of the `manager` and `coursecreator` RBAC groups hold Moodle's Manager and Course creator roles in the system context, members of the `administrator` group are site administrators. `auth_ldap` maps the `manager` and `coursecreator` group DNs at every LDAP login. With `sso` or `ldap` enabled, `tasks/07_rbac.yml` registers [`files/php/provision/rbac.php`](./files/php/provision/rbac.php) as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/), which converges both system roles and `$CFG->siteadmins` at every deploy and on its timer: it creates the account of a member that has none yet, assigns the roles of every member and removes them from every other account. The bootstrap administrator stays the first site administrator, and the bootstrap administrator, the MCP account and `guest` keep their role assignments.

## Object storage

With the `seaweedfs` service enabled the role bakes the GPL plugin [`tool_objectfs`](https://github.com/catalyst/moodle-tool_objectfs) into the image at `admin/tool/objectfs` and makes it Moodle's file system.

| Property | Value |
| --- | --- |
| Pin | commit `MOODLE_OBJECTFS_PLUGIN_COMMIT` on `MOODLE_404_STABLE` (upstream publishes no tags; that head declares `$plugin->supported = [404, 405]`) |
| File system | `$CFG->alternative_file_system_class = '\tool_objectfs\s3_file_system'` |
| Settings | `$CFG->forced_plugin_settings['tool_objectfs']` in `files/build/config.php`, fed from `lookup('objstore', application_id, …)` |
| Transfer | `tool_objectfs\task\push_objects_to_storage`, run every minute by the `cron` service |

`minimumage` and `sizethreshold` are forced to `0`, so an uploaded file is a push candidate on the next task run instead of after the upstream ten-minute / 10 KB thresholds.

`files/build/patch/tool-objectfs-path-style.patch` forces `use_path_style_endpoint` on the AWS SDK client. The plugin exposes no setting for it and the SDK defaults a custom endpoint to virtual-host addressing, which SeaweedFS does not serve. `files/build/install/tool-objectfs.sh` applies it with `patch -F0` and fails the image build if the hunk no longer matches or if upstream starts setting the option itself.

`tasks/utils/objectfs.yml` copies the plugin from the image into the persistent code volume, runs `admin/cli/upgrade.php`, then writes `MOODLE_OBJECTFS_READY_FILE` into the code volume and purges the caches. `files/build/config.php` names `alternative_file_system_class` only once that file exists, so `install_database.php` and the plugin's own upgrade run on Moodle's default file system. The plugin directory is not usable as that signal: `files/build/moodle-entrypoint.sh` copies the whole image tree into the code volume at container start, before any Ansible task runs.

## MCP server

The role exposes a Model Context Protocol surface through the `webservice_mcp` protocol plugin, baked into the image at `public/webservice/mcp` and served by the NGINX sidecar.

| Property | Value |
| --- | --- |
| Endpoint | `/webservice/mcp/server.php` on the canonical domain |
| Container URL | `http://nginx:80/webservice/mcp/server.php` on the shared MCP overlay |
| Transport | Streamable HTTP (JSON-RPC 2.0 over `POST`) |
| Auth | `Authorization: Bearer <token>`, a Moodle web-service token |
| Subject | the `administrator` account |
| Default state | off; `mcp.enabled` turns true when `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is in the inventory |

Provisioning runs in `tasks/utils/mcp.yml`: it copies the plugin into the code volume, runs `admin/cli/upgrade.php`, enables `enablewebservices`, appends `mcp` to `webserviceprotocols`, creates the `infinito_mcp` external service, attaches the read-only functions, mints the permanent token and stores it under `users.administrator.tokens['web-app-moodle']`.

Tool categories exposed by the external service:

- site metadata (`core_webservice_get_site_info`)
- course catalogue (`core_course_get_courses`, `core_enrol_get_users_courses`)
- user lookup (`core_user_get_users_by_field`)
- calendar events (`core_calendar_get_calendar_events`)

All of them are read-only; `mcp.tools.mutating_tools_enabled` is `false` and no write function is attached.

### Default state

Off. `mcp.enabled` is true only while `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is part of the deployment.

### Authorization subject

`auth_subject: administrator`: the web-service token is issued against the
administrator account, so a call carries that account's rights regardless of who
asked the client. The attached functions are read-only, which bounds what those
rights can do here. Reaching the tool server is gated on the role's `mcp` RBAC
group.

### Canonical origin

Moodle compares every request against `$CFG->wwwroot`. A probe that reaches the endpoint over the internal HTTP origin is answered with a redirect to the canonical HTTPS URL rather than with JSON, so callers must send the canonical `Host` header and `X-Forwarded-Proto: https`.

### How to disable

Remove the MCP client roles, or pin `mcp.enabled: false` for this role. The web-service token is then not issued and the protocol plugin stays unconfigured.

## Outbound HTTP policy

Moodle ships a cURL blocklist that rejects every request to `10.0.0.0/8`, `172.16.0.0/12` and `192.168.0.0/16`, and only permits ports 80 and 443. Both settings gate `\core\files\curl_security_helper`, which `auth_oidc` consults for the Keycloak token exchange and `\core\http_client` consults for the AI provider request. The gateway answers on `192.168.80.0/24`, and on an onion node `container_extra_hosts` pins the Keycloak authority to the Docker bridge gateway, which `NETWORK_DOCKER_ADDRESS_POOLS` draws from `10.208.0.0/12`. With the upstream defaults the OIDC login obtains no token and the AI provider cannot reach the gateway.

The pin does not by itself carry the OIDC back-channel on an onion node. libcurl refuses a `.onion` name in `Curl_resolv()` before it reads its own cache or `/etc/hosts` (curl 8.5.0 `lib/hostip.c:694-701`), so the token, JWKS and userinfo calls `auth_oidc` makes through Moodle's `\curl` never leave the container. `MOODLE_OIDC_SOCKS_PROXY` therefore exports `http_proxy`, `https_proxy` and `no_proxy` into `.env/env` whenever the Keycloak domain ends in `.onion`: libcurl reads the lowercase names, `socks5h://` hands the name to Tor to resolve, and on a clearnet issuer the three keys are not rendered at all. The FPM pool keeps `clear_env = no`, which is what puts the container environment in front of libcurl, and only the `moodle` and `cron` services read `.env/env`.

The pin stays anyway, and removing it as redundant breaks the login again: `\core\files\curl_security_helper::host_is_blocked()` performs a forward `gethostbynamel()` whenever any IP rule is configured and returns blocked when the name does not resolve, so without `/etc/hosts` the Keycloak authority is rejected inside Moodle before libcurl is reached.

`MOODLE_PROXY_EXCLUDED_HOSTS` feeds `no_proxy` and carries `lookup('proxy_excluded_hosts')` (loopback and the object store), `MOODLE_MCP_SERVICE_KEY` and, when the `litellm` service is on, the gateway host. The MCP entry is the `nginx` sidecar that `tasks/utils/mcp/verify.yml` probes with the `curl` binary from inside the container: `plugins/filter/curl.py` emits no `--noproxy`, `container exec` inherits the container environment, and Tor cannot resolve a Docker service name, so without the exemption that probe exhausts its retries and fails the deploy. Clearnet hosts such as the update checker's are deliberately left out, so they travel through Tor like the rest of the node's egress.

`files/build/config.php` therefore assigns `$CFG->curlsecurityblockedhosts` from `MOODLE_EGRESS_BLOCKED_HOSTS` and `$CFG->curlsecurityallowedport` from `MOODLE_EGRESS_ALLOWED_PORTS`, which carries the port of `MOODLE_LITELLM_CHAT_ENDPOINT` when the `litellm` service is enabled. Both arrive as comma-separated `.env/env` values and are expanded to the newline-separated form `\core\files\curl_security_helper` expects. Loopback, `0.0.0.0` and the cloud metadata address stay blocked; the RFC1918 ranges are opened. The Docker address pool and the bridge gateway that serves the pinned Keycloak authority both live inside them.

The helper reads both values straight off `$CFG` on every request, so they belong in `config.php` rather than in the admin database: a deploy-time `admin/cli/cfg.php --set` writes a single row from one container, whereas each swarm replica and the cron container answer their own requests from this file. A setting carried in `config.php` also makes `admin/cli/cfg.php --set` exit 4, which is why no task writes these two names.

This is an accepted trade-off, not an oversight. Moodle offers no allowlist, so a single internal host cannot be permitted without unblocking the range it sits in. The cost is that any account holding a URL-fetching capability, such as `block/rss_client:myaddinstance` or a `repository/url` instance, can make the server issue requests to sibling containers. Grant those capabilities only to roles you trust with that reach, or keep the upstream blocklist and accept that SSO login and the AI surface do not work.

## Image source

This role builds its own Moodle image from upstream Moodle source on top of the official `php:8.3-fpm` base and installs the Composer dependencies that source declares. The NGINX sidecar serves the `public` directory of the code volume and hands every other path to Moodle's router.

## Updates

The image carries the Moodle release pinned as `services.moodle.app_version` in `meta/services.yml`. On start the entrypoint compares that release with the one recorded in the code volume. When the image is newer, it copies the image's tree next to the old one and swaps them once the copy is complete. An image that is older than the recorded release refuses to start. `tasks/01_manager_ops.yml` then runs `admin/cli/upgrade.php`, which migrates the database.

### Intermediate releases

Moodle upgrades a site only from a minimum release, which its `admin/environment.xml` names per branch (5.3 needs 4.4). The image therefore also carries the archive of the release pinned as `services.moodle.transit_version` (the 4.5 LTS), and the build records each shipped release with its minimum source in `/opt/moodle-transit/upgrade-path`.

The entrypoint reads the site's release from `.bootstrap.done` or, for a tree it did not write, from `version.php` or `public/version.php`. When the pinned release does not accept that release, it unpacks the transit release into the code volume, runs its `admin/cli/upgrade.php` and records the transit release only after that run succeeded, so a failed run is repeated on the next start. It then swaps in the pinned release as usual. A site older than every minimum source stops the container with both releases in the log.

Before the swap of an existing site the entrypoint asks the pinned release with `admin/cli/upgrade.php --is-pending` whether the database holds an installed site, and refuses to start when it holds none.

### Bitnami layout

Infinito.Nexus up to v0.10.0 ran the Bitnami image with `moodle_code` at `/bitnami/moodle` and `moodle_data` at `/bitnami/moodledata`. Both volumes keep their names, and the code and the data sit at the volume root in both layouts, so nothing moves. The entrypoint names a code volume whose `config.php` points below `/bitnami` in its log, adopts its release, replaces the tree and the `config.php`, and hands the data volume to `www-data` (uid 33).

Plugins installed through the web interface live only in the code volume and are not carried over to the next release. Declare a plugin under `meta/addons/` so the image ships it.

## Further Resources

- [Moodle Official Website](https://moodle.org/)
- [Moodle Developer Documentation: Docker images](https://moodledev.io/general/app/development/setup/docker-images)
- [moodlehq/moodle-docker](https://github.com/moodlehq/moodle-docker) (extension list reference)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/AEkEpfFy4RJ5Cx42MCTwJ9)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`. Moodle's site administrator is created by `install_database.php` in `tasks/01_manager_ops.yml` and realigned on every pass, both from the `platform_administrator` user, so the native form and the identity provider carry one secret. In the SSO variant `tasks/05_login_methods.yml` sets `alternateloginurl` so `/login/index.php` bounces to the OIDC plugin and `tasks/04_oidc.yml` rewrites every `mdl_user` row to `auth='oidc'`, so no form accepts either secret; the SSO-off variants in `meta/variants.yml` have no OIDC chain to substitute. One env file is rendered per role, not per variant, so the flag has to hold for the worst case.

Biber keeps a runnable journey: `files/playwright/test-ldap-variant.js` drives the native LDAP-bind login and `files/playwright/test-profile-readonly.js` asserts the locked profile fields. The path back to the administrator persona is a deploy step that hands the site administrator a credential the persona env already carries.
