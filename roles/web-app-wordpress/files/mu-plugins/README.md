# WordPress Must-Use Plugins 🔒

## Scope 🎯

This directory holds PHP files that the [web-app-wordpress](../../) role copies into the running container at `/var/www/html/wp-content/mu-plugins/`.

`mu-plugins` is a WordPress core convention for **must-use plugins**. WordPress automatically loads every top-level `*.php` file in that directory before normal plugins, without a database activation record. As a result, code shipped here:

- MUST be loaded on every request as soon as the file is present.
- MUST NOT be deactivated from the `Plugins -> Must-Use` admin screen.
- MUST NOT be placed in a subdirectory, because WordPress does not recurse into `mu-plugins`.

See the [WordPress Must-Use Plugins handbook](https://developer.wordpress.org/advanced-administration/plugins/mu-plugins/) for the upstream contract.

## When to add code here 📋

Put a file in this directory only when the behavior it implements is part of the security or integration contract of this role and MUST remain in effect for every request. Everyday feature plugins SHOULD stay in normal `wp-content/plugins/` and be managed through [05_enable_plugin.yml](../../tasks/05_enable_plugin.yml) so operators can disable them per site if needed.

Each file in this directory SHOULD declare its purpose and the hooks it registers at the top of the file so readers can understand why it cannot be switched off.

## OIDC -> RBAC mapping (infinito-oidc-rbac-mapper.php) 🎫

[infinito-oidc-rbac-mapper.php](infinito-oidc-rbac-mapper.php) implements the OIDC -> WordPress role contract:

- **Single-Site path**: the claim MUST contain `/roles/web-app-wordpress/<role>` entries. The highest-privilege role across all matches wins (`administrator > editor > author > contributor > subscriber`). When no entry matches, the user's role is set to `subscriber` as a deterministic fallback.
- **Multisite path** (auto-detected via `is_multisite()`): per-site roles come from `/roles/web-app-wordpress/<canonical-domain>/<role>` entries; the super-admin capability comes from `/roles/web-app-wordpress/network-administrator`. The mapper adds the user to any site they have a role for (`add_user_to_blog`) and removes them from sites it previously added them to (`remove_user_from_blog`) when a role for that site disappears from the claim. A user-meta marker (`_infinito_oidc_added_blog_ids`) records which blog memberships the mapper owns, so memberships added through `wp-admin` or the REST API outside the OIDC flow are never touched.

For the broader RBAC contract (LDAP layout, `rbac.tenancy` schema, the `rbac_group_path` lookup plugin), see [rbac.md](../../../../docs/contributing/design/iam/rbac.md).

## HTTP CA trust (infinito-http-ca-trust.php) 🔐

[infinito-http-ca-trust.php](infinito-http-ca-trust.php) points WordPress's HTTP API at the deployment's CA bundle so outbound calls to internal HTTPS endpoints (OIDC discovery, REST loopback) verify instead of failing.

## HTTP onion SOCKS (infinito-http-onion-socks.php) 🧅

[infinito-http-onion-socks.php](infinito-http-onion-socks.php) sends server-side `wp_remote_*` calls whose host ends in `.onion` through the Tor SOCKS proxy named by `WORDPRESS_OIDC_SOCKS_PROXY`, which [env.j2](../../templates/env.j2) sets only when the OIDC issuer is an onion, so a clearnet deployment never routes through Tor.

It hooks `http_api_curl` rather than `http_request_args` because the args array cannot express a proxy: WordPress core's `WP_HTTP_Proxy` hardcodes `CURLPROXY_HTTP`, so SOCKS5 is reachable only on the raw cURL handle. Without it, libcurl refuses an `.onion` host at name resolution under [RFC 7686](https://www.rfc-editor.org/rfc/rfc7686) — before `/etc/hosts`, `extra_hosts` or DNS is consulted — and the token exchange fails with cURL error 6, which WordPress surfaces as `wp-login.php?login-error=http_request_failed`.

## Deployment 🚚

Every file here is declared as an addon under [meta/addons/](../../meta/addons/) with `mechanism: mu_plugin` and `source: vendored`, and the addon id is the file stem. [04_mu_plugins.yml](../../tasks/04_mu_plugins.yml) loops over those declarations and copies `<addon_id>.php` into the container on every deploy; a new file therefore needs its `meta/addons/<addon_id>.yml` entry and a Playwright spec before it is installed.

## Credits 🙏

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
