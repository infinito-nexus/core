# WordPress Must-Use Plugins 🔒

## Scope 🎯

This directory holds PHP files that the [web-app-wordpress](../../) role copies into the running container at `/var/www/html/wp-content/mu-plugins/`.

`mu-plugins` is a WordPress core convention for **must-use plugins**. WordPress automatically loads every top-level `*.php` file in that directory before normal plugins, without a database activation record. As a result, code shipped here:

- MUST be loaded on every request as soon as the file is present.
- MUST NOT be deactivated from the `Plugins -> Must-Use` admin screen.
- MUST NOT be placed in a subdirectory, because WordPress does not recurse into `mu-plugins`.

See the [WordPress Must-Use Plugins handbook](https://developer.wordpress.org/advanced-administration/plugins/mu-plugins/) for the upstream contract.

## When to add code here 📋

Put a file in this directory only when the behavior it implements is part of the security or integration contract of this role and MUST remain in effect for every request. Everyday feature plugins SHOULD stay in normal `wp-content/plugins/` and be managed through [06_enable_plugin.yml](../../tasks/06_enable_plugin.yml) so operators can disable them per site if needed.

Each file in this directory SHOULD declare its purpose and the hooks it registers at the top of the file so readers can understand why it cannot be switched off.

## OIDC -> RBAC mapping (infinito-oidc-rbac-mapper.php) 🎫

[infinito-oidc-rbac-mapper.php](infinito-oidc-rbac-mapper.php) implements the OIDC -> WordPress role contract:

- **Group map**: the mapper matches the claim named by `WORDPRESS_OIDC_CLAIM_GROUPS` against `WORDPRESS_RBAC_GROUP_MAP`, which [env.j2](../../templates/env.j2) renders from [rbac_group_map.json.j2](../../templates/rbac_group_map.json.j2). Group paths not in the map are ignored.
- **Single-Site path**: the claim MUST contain `/roles/web-app-wordpress/<role>` entries. The highest-privilege role across all matches wins (`administrator > editor > author > contributor > subscriber`). When no entry matches, the user's role is set to `subscriber` as a deterministic fallback.
- **Multisite path** (auto-detected via `is_multisite()`): per-site roles come from `/roles/web-app-wordpress/<canonical-domain>/<role>` entries and network-wide site roles from `/roles/web-app-wordpress/global-<role>` entries, which the map carries for every `global-<role>` the deployment declares; the super-admin capability comes from `/roles/web-app-wordpress/network-administrator`. On every site but the user's own site, the highest of the global roles and that site's per-site roles wins, so no login lowers a role the groups grant there. The mapper adds the user to any site they have a role for (`add_user_to_blog`) and removes them from sites it previously added them to (`remove_user_from_blog`) when the claim names no role for that site any more. A user-meta marker (`_infinito_oidc_added_blog_ids`) records which blog memberships the mapper owns; a membership added through `wp-admin` or the REST API outside the OIDC flow is never removed, and becomes Subscriber while the claim names no role for its site.
- **Own site**: only when `WORDPRESS_SITE_OWNER_ENABLED` is `true`. For a member of `/roles/web-app-wordpress/site-owner` the mapper finds the site `<login>.<host of WORDPRESS_SITE_OWNER_BASE_URL>`. It creates the site with the member as administrator when it is missing, recording the `sub` claim in the site meta `infinito_site_owner_subject`, restores it when it is archived and keeps the member its administrator. For a user outside the group it archives that site, keeping its content. It only acts on a site whose recorded subject matches, or on a site that `infinito_rbac_reserve_own_site()` reserved for the login through `infinito_site_owner_login` at deploy. The first sign-in claims a reserved site: it records the subject and removes every other member, the deploy's interim administrator included. The per-site loop skips the own site. When this step fails, the loop still skips the site on the own domain of the account's login while the groups grant `site-owner` and the site records the member, so neither a failed step nor a global role lowers its owner; a former owner or a foreign site gets the same treatment as any other site. A login the member label rule refuses, a login claim other than the account's login, a missing subject or a foreign site is logged and skips only this step, so the sign-in still completes. At deploy, `infinito_rbac_archive_reserved_sites_of_former_members()` archives every own site whose login is no longer an inventory member and ends its owner's sessions.
- **Super-admin**: the mapper grants super-admin to members of the network-administrator group and records the grant in `_infinito_oidc_granted_super_admin`. It revokes only a grant it recorded, so the bootstrap administrator and super-admins set in `wp-admin` keep their rights.
- **Profile sync**: on every OIDC login the mapper writes `first_name`, `last_name`, `display_name`, `user_email`, `user_url` and `locale` from the claims named by the `WORDPRESS_OIDC_CLAIM_*` variables. The locale becomes an installed WordPress language when one matches, its `ll_CC` form otherwise. An email change sends no notification mail.
- **Read-only profile fields**: for an account that carries the `openid-connect-generic-subject-identity` meta, the `admin_body_class` filter adds `infinito-sso-managed` to the `body` of `profile.php` and `user-edit.php`; the selectors of the role's `sso.<claim>` fields in `meta/forms.yml` start with that class, so the shared lock renderer of `sys-front-inj-javascript` renders the locked inputs read-only and disables the locked selects, with the translated warning as their hover title. `WORDPRESS_OIDC_PROFILE_LOCKED` lists the keys of those fields, and `INFINITO_OIDC_LOCKABLE_FIELDS` maps each key to its stored field and its `profile.php` input (table below). The `personal_options_update` hook restores each locked input to its stored value or drops it from a `profile.php` save, so WordPress mails no confirmation link to a submitted address, and the `wp_pre_insert_user_data` and `insert_user_meta` filters keep the locked columns and meta on every other `wp_insert_user` write (`user-edit.php`, `/wp/v2/users`, XML-RPC `wp.editProfile`, plugins), except the login's profile sync and WP-CLI. While `email` is locked, an email change of an OIDC account mails no change notice. A field whose key the list does not hold stays editable; the next OIDC login still overwrites it. An unknown key, an empty list or a value that is no JSON list raises on the first guarded write of an OIDC account and names the variable or the key.

| Key            | Stored field                | `profile.php` input            |
|----------------|-----------------------------|--------------------------------|
| `first_name`   | user meta `first_name`      | `first_name`, restored         |
| `last_name`    | user meta `last_name`       | `last_name`, restored          |
| `display_name` | users column `display_name` | `display_name`, dropped        |
| `email`        | users column `user_email`   | `email`, restored              |
| `website`      | users column `user_url`     | `url`, restored                |
| `language`     | user meta `locale`          | `locale`, dropped              |

For the broader RBAC contract (LDAP layout, `rbac.tenancy` schema, the `rbac_group_path` lookup plugin), see [rbac.md](../../../../docs/contributing/design/iam/rbac.md).

## OIDC client settings and member sign-in (infinito-oidc-client.php) 🔑

[infinito-oidc-client.php](infinito-oidc-client.php) acts only when `WORDPRESS_SSO_ENABLED` is `true` and refuses to load when the variable is unset.

- **Settings**: `pre_option_openid_connect_generic_settings` answers on every site from `WORDPRESS_OIDC_SETTINGS`, so a site created at sign-in has its client at once. `pre_update_option` keeps the settings in force for every writer, WP-CLI included, and the deploy deletes any stored copy on every site through [settings.php](../php/oidc/settings.php).
- **Settings page**: the plugin's options page is missing from every menu and its URL answers 403 to every account, the network administrators included.
- **Member sign-in**: on a host one label below the parent of `WORDPRESS_SITE_OWNER_BASE_URL` that carries an existing own site, `wp-login.php` redirects with its query to the main site's `wp-login.php` before the plugin's auto-login runs, and `allowed_redirect_hosts` lets the sign-in return to that host.

## AI Engine network guard (infinito-ai-engine-network.php) 🤖

[infinito-ai-engine-network.php](infinito-ai-engine-network.php) acts only on Multisite. `mwai_allow_setup` keeps the AI Engine settings to the network administrators. `option_mwai_options` and `default_option_mwai_options` turn `module_mcp` off and drop `mcp_bearer_token` on every site but the main site, so AI Engine registers no `mcp/v1` route there. The deploy clears both keys from the stored options of those sites through [network_mcp.php](../php/ai_engine/network_mcp.php).

## Managed options (infinito-managed-options.php) 🔒

[infinito-managed-options.php](infinito-managed-options.php) keeps every option the deployment manages at its managed value for every writer: the settings pages, the REST API, plugins and WP-CLI. `WORDPRESS_MANAGED_OPTIONS` in [vars/main.yml](../../vars/main.yml) holds those values, built only from `lookup('form_values', ...)` of [meta/forms.yml](../../meta/forms.yml): `option` for the main site, the address included on a single site, and `site_option` for the network.

- **Values file**: the first task of [07_manager_ops.yml](../../tasks/07_manager_ops.yml) hands the values on stdin to [managed_options.php](../php/managed_options.php), which runs on the container's PHP CLI without booting WordPress and writes them as a PHP file that returns them, to the path `WORDPRESS_MANAGED_OPTIONS_FILE` names in [env.j2](../../templates/env.j2). The file is mode `0600` from its first byte, written under `umask 0077` and moved into place, so no other account reads it and a request for it over HTTP runs it and serves nothing. The values never land in a file on the host.
- **Guard**: the plugin answers `pre_update_option_<name>` of every `option` on the main site and `pre_update_site_option_<name>` of every `site_option` with the managed value, at the last priority, so a write stores the managed value whoever sends it. An array option under `merge` keeps only its managed parts: each managed key, and each managed record of a list in place of the stored record with its `id`, while every other key and record stays as written. AI Engine's `mwai_options` is one: its `ai_default_env`, its `ai_default_model` and the `infinito-litellm` environment in `ai_envs`, endpoint and API key included, come from the `ai_engine` form, a `native` form, so an environment an administrator adds stays editable. A read stays untouched, so the deploy's drift report still sees a value written past the guard.
- **Fail closed**: the plugin throws when `WORDPRESS_MANAGED_OPTIONS_FILE` is unset or its file returns no `option` and `site_option` map, so no request runs while a managed option could change. The deploy writes the file before any WordPress command, which repairs a lost file on the next run.

## Corporate design (infinito-design.php) 🎨

[infinito-design.php](infinito-design.php) acts only while the `infinito_design` option holds the design that [design.php](../php/design.php) wrote. It registers the corporate admin color scheme, styles the sign-in page and hands the design tokens to the editor canvas.

- **Guard**: `pre_update_option_site_icon` and `pre_update_option_site_logo` answer with the attachment the deploy wrote, and `wp_insert_post_data` puts the deploy's global styles into the `wp_global_styles` post of each theme it styles, both at the last priority, so the Customizer, the Site Editor, the REST API and WP-CLI keep the design. Only design.php, which defines `NEXUS_DESIGN_WRITER`, writes past the guard. An option or post deleted outright, for example through `wp option delete`, stays deleted until the next deploy writes it again.
- **Every deploy** writes the site icon, the site logo and the global styles again. Before that write, [design_drift.php](../php/design_drift.php) reads each part the site holds other than the last deploy wrote it, and the deploy reports it as drift. Turning the design off withdraws only what the deploy wrote.

## HTTP CA trust (infinito-http-ca-trust.php) 🔐

[infinito-http-ca-trust.php](infinito-http-ca-trust.php) points WordPress's HTTP API at the deployment's CA bundle so outbound calls to internal HTTPS endpoints (OIDC discovery, REST loopback) verify instead of failing.

## HTTP onion SOCKS (infinito-http-onion-socks.php) 🧅

[infinito-http-onion-socks.php](infinito-http-onion-socks.php) sends server-side `wp_remote_*` calls whose host ends in the suffix of the tor network through the Tor SOCKS proxy named by `WORDPRESS_OIDC_SOCKS_PROXY`. [env.j2](../../templates/env.j2) sets both variables only when the OIDC issuer is an onion, `WORDPRESS_OIDC_SOCKS_SUFFIX` from the network registry through `network_suffix`, so a clearnet deployment never routes through Tor.

It hooks `http_api_curl` rather than `http_request_args` because the args array cannot express a proxy: WordPress core's `WP_HTTP_Proxy` hardcodes `CURLPROXY_HTTP`, so SOCKS5 is reachable only on the raw cURL handle. Without it, libcurl refuses an `.onion` host at name resolution under [RFC 7686](https://www.rfc-editor.org/rfc/rfc7686) — before `/etc/hosts`, `extra_hosts` or DNS is consulted — and the token exchange fails with cURL error 6, which WordPress surfaces as `wp-login.php?login-error=http_request_failed`.

## Network origins (infinito-network-origins.php) 🌐

[infinito-network-origins.php](infinito-network-origins.php) moves every site URL into the network the request's `Host` belongs to. `INFINITO_NETWORK_BASE_URLS` in [env.j2](../../templates/env.j2) lists the network siblings of each site, canonical network first, separated by `,`, and the sites by `;` (`WORDPRESS_NETWORK_BASE_URLS` in [vars/main.yml](../../vars/main.yml)). A URL whose host is a known site sibling is answered with that site's sibling in the request's network, for the `home` and `siteurl` options, `content_url`, `plugins_url`, `network_home_url`, `network_site_url` and `upload_dir`. `WP_CONTENT_URL` and `WP_PLUGIN_URL` are fixed from `siteurl` before any mu-plugin loads, which is why the URL filters are needed as well. The stored options keep the canonical URL, so WP-CLI and requests on any other host read them unchanged.

On Multisite, [03_multisite.yml](../../tasks/03_multisite.yml) also copies the same file to `wp-content/sunrise.php` and sets `SUNRISE`. WordPress looks the site up by `Host` before any mu-plugin runs, so a sibling host would match no site and get redirected to the clearnet `wp-signup.php`. Loaded as the drop-in, the file answers `pre_get_site_by_path` for a sibling host with the site of its canonical host. It also sets `COOKIE_DOMAIN` for every site host: the network domain's sibling in the request's network for a host at or below it, and a host-only cookie for a child on its own domain (such as `biberblog.<primary>`), because a browser drops a cookie whose domain the host does not match. A constant guard keeps the second load from mu-plugins from registering anything twice.

## Deployment 🚚

Every file here is declared as an addon under `meta/addons/` with `mechanism: mu_plugin` and `source: vendored`, and the addon id is the file stem. [04_mu_plugins.yml](../../tasks/04_mu_plugins.yml) loops over those declarations and copies `<addon_id>.php` into the container on every deploy; a new file therefore needs its `meta/addons/<addon_id>.yml` entry and a Playwright spec before it is installed.

## Credits 🙏

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
