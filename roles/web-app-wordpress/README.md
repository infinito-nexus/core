# WordPress

## Description

[WordPress](https://en.wordpress.org/) is a versatile and widely used [content management system (CMS)](https://en.wikipedia.org/wiki/Content_management_system) that powers millions of websites, from blogs and portfolios to e-commerce and corporate sites. This deployment provides a containerized WordPress instance optimized for multisite operation, advanced media management, and extensive plugin support, allowing you to fully leverage the rich features of the WordPress software.

## Overview

WordPress offers an extensive array of features that make it a robust platform for building and managing digital content:

- **User-Friendly Interface:**
  Enjoy a modern, intuitive dashboard for effortless content creation, editing, and management.

- **Customizable Themes and Plugins:**
  Extend your site's functionality with thousands of themes and plugins, enabling you to tailor your website's look, feel, and capabilities to your exact needs.

- **Multisite Management:**
  Easily create and maintain multiple sites with a single WordPress installation, ideal for networks of blogs, corporate intranets, or educational institutions.

- **Responsive Design:**
  Ensure that your website looks great on all devices with mobile-friendly themes and layouts.

- **Advanced SEO Tools:**
  Optimize your site's visibility in search engines using built-in support for SEO best practices and a rich ecosystem of SEO plugins.

- **Robust Media Management:**
  Manage your images, videos, and other media with an integrated media library, including options for enhanced upload limits and dynamic content delivery.

- **Extensive Community and Ecosystem:**
  Benefit from a massive community with frequent updates, security patches, and a wide range of third-party tools that continuously enhance the platform.

This automated Docker Compose deployment streamlines the process by building a custom WordPress image (which includes tools like msmtp for email delivery) and configuring the necessary PHP settings, ensuring that your WordPress site is secure, scalable, and always up to date.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.
- **OIDC profile sync:** Every OIDC login overwrites the WordPress first name, last name, display name, email, website and language of the user with the Keycloak claims, so Keycloak stays the source of the profile.
- **Read-only IdP fields:** the `sso.<claim>` fields of [`meta/forms.yml`](./meta/forms.yml) decide which fields are locked. [`templates/env.j2`](./templates/env.j2) renders their keys into `WORDPRESS_OIDC_PROFILE_LOCKED` through `lookup('field_locks', application_id).profile`. On `profile.php` and `user-edit.php` of an OIDC account those fields are read-only with a translated warning as their hover title, rendered by the shared lock renderer of `sys-front-inj-javascript`. Every write through `wp_insert_user` (the profile and user forms, `/wp/v2/users`, XML-RPC `wp.editProfile`, any plugin calling `wp_update_user`) keeps their stored values, except the profile sync of the OIDC login itself. Removing such a field unlocks it in the form and on every write; the next OIDC login still overwrites it.
- **Break-glass editing:** WP-CLI (`wp user update`) is the one path that changes the IdP-managed fields of an OIDC account; the next OIDC login overwrites them again.
- **OIDC role mapping:** Every OIDC login sets the WordPress role from the user's Keycloak role groups; a user without one is a Subscriber.
- **Multisite RBAC:** Under Multisite, per-site groups set the role on each site, a `global-<role>` group sets that role on every site of the network, and the higher of both wins on each site. The network-administrator group grants super-admin and revokes the super-admin rights it granted. The bootstrap administrator keeps its super-admin rights.
- **Login methods:** `services.wordpress.login.method` declares `sso`, `native` and `registration` (see [Login Methods](../../docs/contributing/design/iam/login.md)). `sso` enables the `daggerhart-openid-connect-generic` addon. With `sso` on, `native` sets the addon's `login_type`: `auto` (the default, `wp-login.php` redirects to Keycloak) while `native` is off, `button` (form plus Keycloak button) while it is on; without `sso` the WordPress form is the only sign-in. `registration` sets `users_can_register` (`1` or `0`), or the network option `registration` (`user` or `none`) under Multisite, as the managed fields of the same names in [meta/forms.yml](meta/forms.yml); `services.wordpress.multisite.enabled` picks the field, so a deploy whose installation reports another `is_multisite()` fails before any option is written. WordPress core has no second factor and the role no `ldap` service, so neither is declared.
- **Break-glass access:** with SSO on, the addon skips its redirect for a request that posts `wp-submit`, so the local administrator (`WORDPRESS_ADMIN_USERNAME`) signs in with a direct `POST /wp-login.php` carrying `log`, `pwd` and `wp-submit` (e.g. `curl -c jar -d log=<user> -d pwd=<password> -d wp-submit=1 <url>/wp-login.php`); `files/playwright/test-login-methods.js` proves it. WP-CLI inside the container stays available as well.
- **WordPress options from the configuration:** [meta/forms.yml](meta/forms.yml) declares every option the role writes, each with the inventory `source` it converges from: `blogname` (Site Title) is `services.design.title` while the `design` service is on, `admin_email` is the platform administrator's email, `users_can_register` and the network's `registration` follow the `registration` login method, `permalink_structure` is `services.wordpress.options.permalink_structure`, and the FreedomTranslate options are the `config.options` of the `freedomtranslate-wp` addon while that addon is on. `WORDPRESS_OPTIONS` and `WORDPRESS_NETWORK_OPTIONS` in [main.yml](vars/main.yml) read them only through `lookup('form_values', ...)`; meta/forms.yml names them as the `sinks` of their forms, so the forms lint fails on a value from anywhere else, and [utils/options.yml](tasks/utils/options.yml) writes each with `wp option update` or `wp site option update` whenever WordPress stores a different value; a write that changes the stored value flushes the rewrite rules. Every deploy therefore sets each managed option back to its source: before the write, [drift.yml](../../tasks/utils/forms/drift.yml) logs each managed option a wp-admin edit changed and raises the journal event the Loki ruler alerts on, and the settings pages lock the managed fields with the sentence that the deployment manages them. Between deploys the [infinito-managed-options](files/mu-plugins/README.md#managed-options-infinito-managed-optionsphp-) mu-plugin keeps each managed option at its managed value for every writer, REST API and WP-CLI included, so a save no longer changes it. An inventory sets another option by pinning it under `applications.web-app-wordpress.services.wordpress.options.<name>` and declaring its field, with that pin as `source`, under `applications.web-app-wordpress.forms`; the key carries `# nocheck: inventory-open-subtree`, so the inventory validator accepts names [services.yml](meta/services.yml) does not declare, and a pin no field reads fails the deploy. Options the role computes or WordPress manages (`WORDPRESS_OPTIONS_OWNED_ELSEWHERE` in [main.yml](vars/main.yml)), keys that name a secret and a `true` or `false` design title while the design is on are refused. `permalink_structure` is pinned to `/blog/%year%/%monthnum%/%day%/%postname%/`, the structure the blog published its post URLs under.
- **Site address:** on a single site the `address` form of [meta/forms.yml](meta/forms.yml) manages `siteurl` (WordPress Address) and `home` (Site Address) from `services.wordpress.address`, the role's TLS origin. `WORDPRESS_ADDRESS` in [main.yml](vars/main.yml) carries them to [08_update_domain.yml](tasks/08_update_domain.yml), which reads the stored `home` first, converges both through [utils/options.yml](tasks/utils/options.yml) with its drift report, and then rewrites the old address to the new one across the database. Under Multisite the form does not apply.
- **Corporate design:** while `services.design.enabled` is on, every deploy writes the site icon, the site logo and the global styles of `twentytwentyfive` through [09_design.yml](tasks/09_design.yml). Before the write, [design_drift.php](files/php/design_drift.php) reads each of them the site holds other than the last deploy wrote it, and [drift_report.yml](../../tasks/utils/forms/drift_report.yml) logs it as `web-app-wordpress: design.<part>: changed` and raises the journal event the Loki ruler alerts on. Between deploys the [infinito-design](files/mu-plugins/README.md#corporate-design-infinito-designphp-) mu-plugin keeps them for every writer, the Customizer, the Site Editor, the REST API and WP-CLI included, so an administrator no longer replaces them while the design is on. Turning the design off withdraws only what the deploy wrote.

## Purpose

The goal of this deployment is to provide a production-ready, scalable WordPress instance with multisite capabilities and enhanced performance. By automating the custom image build and configuration processes via Docker Compose and Ansible, it minimizes manual intervention, reduces errors, and allows you to concentrate on building great content.

## Multisite

WordPress Multisite is opt-in. Set `services.wordpress.multisite.enabled: true` in the inventory to convert the deployed instance into a sub-domain Multisite network. Every entry in `domains.canonical` becomes the site of exactly that domain in the network; the first entry is the network primary, subsequent entries are child sites. [files/php/multisite/sites.php](files/php/multisite/sites.php) creates them and moves a site that an earlier deploy created at `<domain>.<network domain>` to `<domain>`.

RBAC under Multisite uses the hierarchical Keycloak group path:

- Per-site role: `/roles/web-app-wordpress/<canonical-domain>/<role>`
- Site role on every site of the network: `/roles/web-app-wordpress/global-<role>`
- Network-wide super-admin: `/roles/web-app-wordpress/network-administrator`
- Own site: `/roles/web-app-wordpress/site-owner`

A member of `site-owner` administers the site `<username>.<parent>`, where `domains.served` in the Multisite variant sets the parent to `user.blog.<DOMAIN_PRIMARY>`, which a tor-only node serves as its onion sibling `user.blog.<node>.onion`. Only a Keycloak username (`[a-z1-9]`, or the agent form `<4 chars>0<suffix>`) of at most 63 characters that is no WordPress `illegal_names` entry names a site. The mapper creates the site on the member's first SSO login, records the member's OIDC subject on it and only ever takes over or archives a site that carries that subject or that the deploy reserved for the login. An SSO login outside the group archives the site and keeps its content, a login back in the group restores it. A deploy applies a membership change as well: [tasks/05_site_owners.yml](tasks/05_site_owners.yml) archives every own site whose login is no longer an inventory member and ends that member's sessions.

Where WordPress can certify a wildcard (no TLS, self-signed, or the Let's Encrypt `wildcard` flavor on a DNS challenge), one vhost serves `*.<parent>`, so a site is reachable as soon as the mapper creates it. Everywhere else every inventory user holding `site-owner` gets a vhost and a certificate for `<username>.<parent>`, and [tasks/05_site_owners.yml](tasks/05_site_owners.yml) reserves the site at deploy, administered by the deploy's administrator until the member's first sign-in claims it. A sign-in on a member host runs on the network's main site, whose auth cookie the network domain shares, so Keycloak needs no redirect URI per member. The SSO client settings come from the container on every site through `infinito-oidc-client`; no account opens or changes them, and the deploy deletes any stored copy.

The `ai_engine` form of [meta/forms.yml](meta/forms.yml) manages AI Engine's default environment, its default model and the endpoint and API key of the `infinito-litellm` environment. Behaviour change: between deploys `infinito-managed-options` keeps them on every write of `mwai_options`, an environment an administrator adds stays editable, and every deploy reports a changed endpoint, default environment or model before it writes them back; the API key never leaves the container for that report.

On Multisite, `infinito-ai-engine-network` keeps the AI Engine settings to the network administrators and its MCP server to the main site, because an AI Engine bearer token signs in as the first administrator of its site, which can be a network administrator.

The Multisite variant in [meta/variants.yml](meta/variants.yml) sets `rbac.tenancy.axis: domain`, declares `network-administrator`, `site-owner` and one `global-<role>` per site role with `scope: global`, keeps `mcp` global and declares the `domains.served` parent of the `site-owner` sites. [rbac_group_map.json.j2](templates/rbac_group_map.json.j2) builds every group path with `rbac_group_path`, maps a `global-<role>` only where the deployment declares it, and hands the map to the mu-plugin as `WORDPRESS_RBAC_GROUP_MAP`. A deploy that enables Multisite without `rbac.tenancy.axis: domain` fails in [tasks/00_core.yml](tasks/00_core.yml) with a message naming the missing tenancy, before the role deploys anything.

Operator-facing instructions for assigning these groups live in [Administration RBAC](../../docs/administration/configuration/rbac.md). The design contract is in [RBAC design](../../docs/contributing/design/iam/rbac.md).

## Addons

Every plugin and mu-plugin is declared in `meta/addons/` under
the unified addon contract. The OIDC and WP-Discourse runtime config lives in each addon's `config:` block. Both install paths read those declarations: a `required` addon that fails to install stops the deploy, an optional one warns and is skipped.

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `daggerhart-openid-connect-generic` | `plugin` | enabled with the `sso` login method, which follows the `sso` service | `sso` → `web-app-keycloak` |
| `wp-discourse` | `plugin` | enabled with the `discourse` service | `discourse` → `web-app-discourse` |
| `activitypub` | `plugin` | enabled in variant 0 (Fediverse federation); off in later variants | none |
| `infinito-oidc-rbac-mapper` | `mu_plugin` | `required`, enabled with the `sso` service (always copied, vendored) | `sso` → `web-app-keycloak` |
| `infinito-oidc-client` | `mu_plugin` | enabled with the `sso` service and login method (always copied, vendored) | `sso` → `web-app-keycloak` |
| `infinito-ai-engine-network` | `mu_plugin` | enabled with `ai-engine` (always copied, acts only on Multisite, vendored) | none |
| `infinito-http-ca-trust` | `mu_plugin` | `required` (always installed, vendored) | none |
| `infinito-managed-options` | `mu_plugin` | `required` (always installed, vendored) | none |
| `s3-uploads` | `plugin` | enabled with the `seaweedfs` service | none |
| `infinito-s3-uploads` | `mu_plugin` | enabled with the `seaweedfs` service | none |

The OIDC plugin finds an account only by the Keycloak user id it stored for it (the `sub` claim, user meta `openid-connect-generic-subject-identity`). `link_existing_users` is off: plugin 3.11.4 lets a verified email match replace the identity an account is already bound to, so a new Keycloak user holding a reused address could take over that account. A sign-in without a bound account creates a new one. An email that already belongs to an account fails that sign-in closed; a user name that is already taken does not, the plugin creates the account under the next free name (`<name>2`). Every deploy binds the install administrator to the id of the Keycloak user with the same name, removes that id from every other account under each site-prefixed key that holds it, and fails when any other account, under any site prefix, still holds it; the deploy log names each account and key it unbound. Before the bind writes anything, the deploy fails when the administrator already carries a different id under any subject-identity key and names each such key, not its value; an operator checks which Keycloak user that value belongs to, clears the key with `wp user meta delete <administrator> <key>` and deploys again. The bind reads the id from the local Keycloak, so a deploy with this addon fails before it touches WordPress when `OIDC_OVERRIDE` points WordPress at another issuer. A WordPress user that existed before and was never bound can no longer link itself; an administrator binds it in two steps. First, find every other account that holds the Keycloak user id under the global or a site-prefixed subject-identity key (`wp user list --blog_id=0 --meta_key=openid-connect-generic-subject-identity --meta_compare_key=LIKE --meta_value=<id> --fields=ID,user_login`), list that account's keys ending in `openid-connect-generic-subject-identity` (`wp user meta list <account> --fields=meta_key`), and remove the id under each of those keys that holds it (`wp user meta delete <account> <key> <id>`). Then set `openid-connect-generic-subject-identity` on the user to the Keycloak user id.

The OIDC login + RBAC paths are covered by `test-admin-oidc-login.js` /
`test-rbac-roles.js` / `test-multisite-rbac.js`, the profile sync by `test-profile-sync.js`, the profile lock with its warning on `profile.php` and `user-edit.php` and against direct form, REST and XML-RPC writes by `test-profile-lock.js`, the Discourse round-trip by `test-discourse-roundtrip.js`.

## Playwright service dependencies

The Playwright suite in [files/playwright/playwright.spec.js](files/playwright/playwright.spec.js) gates its scenarios on the following shared services. Scenarios that depend on a service report as `skipped` when the corresponding `<SERVICE>_SERVICE_ENABLED=false` in the staged `.env`:

- `oidc`: baseline admin OIDC round-trip, the three Single-Site RBAC scenarios (subscriber/editor/administrator), the Multisite scenarios (bootstrap super-admin kept, network-administrator grant and revoke, per-site Editor on the primary and on a child site only, own site created, archived and restored through site-owner) and the profile sync and read-only scenario.
- `javascript`: the profile lock scenarios in `test-profile-lock.js` and the read-only scenario in `test-profile-sync.js`, whose lock the shared lock renderer injects.
- `discourse`: the WP->Discourse post round-trip scenario. Disabling Discourse skips it; front-page reachability and CSP baselines stay active.
- `seaweedfs`: the media-library upload scenario in `test-seaweedfs.js`, which lists the role's bucket over the S3 API before and after the upload.

The front-page CSP + canonical-domain baseline is ungated and always runs.

## Further Resources

- [WordPress Official Website](https://wordpress.org/)
- [WordPress Multisite Documentation](https://wordpress.org/support/article/create-a-network/)
- [WordPress Plugin Repository](https://wordpress.org/plugins/)
- [WP Discourse Plugin](https://wordpress.org/plugins/wp-discourse/)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/FZWdjPsZkLfEqUEe3bQ6zj)

## Persona contract opt-outs

WordPress's canonical surface is the public blog front page. The OIDC round-trip fires on `/wp-login.php`, which the `daggerhart-openid-connect-generic` addon auto-redirects to Keycloak (`login_type: auto` while the `native` login method is off, see [`meta/addons/daggerhart-openid-connect-generic.yml`](./meta/addons/daggerhart-openid-connect-generic.yml)); the shared personas enter at the site root and never visit that path.
[`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The journeys themselves are not dropped: `test-admin-oidc-login.js` drives the admin login, logout and landing assertion, and `test-rbac-roles.js` drives the Keycloak-group-to-WordPress-role mapping over the same entry point.
