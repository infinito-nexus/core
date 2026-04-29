# WordPress Must-Use Plugins 🔒

## Scope 🎯

This directory holds PHP files that the [web-app-wordpress](../../) role copies into the running container at `/var/www/html/wp-content/mu-plugins/`.

`mu-plugins` is a WordPress core convention for **must-use plugins**. WordPress automatically loads every top-level `*.php` file in that directory before normal plugins, without a database activation record. As a result, code shipped here:

- MUST be loaded on every request as soon as the file is present.
- MUST NOT be deactivated from the `Plugins -> Must-Use` admin screen.
- MUST NOT be placed in a subdirectory, because WordPress does not recurse into `mu-plugins`.

See the [WordPress Must-Use Plugins handbook](https://developer.wordpress.org/advanced-administration/plugins/mu-plugins/) for the upstream contract.

## When to add code here 📋

Put a file in this directory only when the behavior it implements is part of the security or integration contract of this role and MUST remain in effect for every request. Everyday feature plugins SHOULD stay in normal `wp-content/plugins/` and be managed through [03_enable_plugin.yml](../../tasks/03_enable_plugin.yml) so operators can disable them per site if needed.

Each file in this directory SHOULD declare its purpose, hooks, and source requirement at the top of the file so readers can understand why it cannot be switched off.

## OIDC -> RBAC mapping (infinito-oidc-rbac-mapper.php) 🎫

[infinito-oidc-rbac-mapper.php](infinito-oidc-rbac-mapper.php) is the only file shipped here today. It implements the OIDC -> WordPress role contract from requirements 004 and 005:

- **Single-Site path**: the claim MUST contain `/roles/web-app-wordpress/<role>` entries. The highest-privilege role across all matches wins (`administrator > editor > author > contributor > subscriber`). When no entry matches, the user's role is set to `subscriber` as a deterministic fallback.
- **Multisite path** (auto-detected via `is_multisite()`): per-site roles come from `/roles/web-app-wordpress/<canonical-domain>/<role>` entries; the super-admin capability comes from `/roles/web-app-wordpress/network-administrator`. The mapper adds the user to any site they have a role for (`add_user_to_blog`) and removes them from sites it previously added them to (`remove_user_from_blog`) when a role for that site disappears from the claim. A user-meta marker (`_infinito_oidc_added_blog_ids`) records which blog memberships the mapper owns, so memberships added through `wp-admin` or the REST API outside the OIDC flow are never touched.

For the broader RBAC contract (LDAP layout, `rbac.tenancy` schema, the `rbac_group_path` lookup plugin), see [rbac.md](../../../../docs/contributing/design/iam/rbac.md).

## Deployment 🚚

Files in this directory are copied into the running container by [05_mu_plugins.yml](../../tasks/05_mu_plugins.yml). The task runs on every deploy, so dropping a new file here is enough to have it picked up on the next playbook run.

## Credits 🙏

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
