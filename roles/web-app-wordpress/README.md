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
- **Read-only IdP fields:** On `profile.php` and `user-edit.php` of an OIDC account these fields are read-only with a translated warning as their hover title. Every write through `wp_insert_user` (the profile and user forms, `/wp/v2/users`, XML-RPC `wp.editProfile`, any plugin calling `wp_update_user`) keeps their stored values, except the profile sync of the OIDC login itself. The fields are declared in `services.sso.profile.locked` and rendered by the shared lock renderer of `sys-front-inj-javascript`.
- **Break-glass editing:** WP-CLI (`wp user update`) is the one path that changes the IdP-managed fields of an OIDC account; the next OIDC login overwrites them again.
- **OIDC role mapping:** Every OIDC login sets the WordPress role from the user's Keycloak role groups; a user without one is a Subscriber.
- **Multisite RBAC:** Under Multisite, per-site groups set the role on each site, and the network-administrator group grants super-admin and revokes the super-admin rights it granted. The bootstrap administrator keeps its super-admin rights.
- **Login methods:** `services.wordpress.login.method` declares `sso`, `native` and `registration` (see [Login Methods](../../docs/contributing/design/iam/login.md)). `sso` enables the `daggerhart-openid-connect-generic` addon. With `sso` on, `native` sets the addon's `login_type`: `auto` (the default, `wp-login.php` redirects to Keycloak) while `native` is off, `button` (form plus Keycloak button) while it is on; without `sso` the WordPress form is the only sign-in. `registration` sets `users_can_register`, or the network option `registration` (`user` or `none`) under Multisite, through WP-CLI in [`tasks/07_manager_ops.yml`](./tasks/07_manager_ops.yml). WordPress core has no second factor and the role no `ldap` service, so neither is declared.
- **Break-glass access:** with SSO on, the addon skips its redirect for a request that posts `wp-submit`, so the local administrator (`WORDPRESS_ADMIN_USERNAME`) signs in with a direct `POST /wp-login.php` carrying `log`, `pwd` and `wp-submit` (e.g. `curl -c jar -d log=<user> -d pwd=<password> -d wp-submit=1 <url>/wp-login.php`); `files/playwright/test-login-methods.js` proves it. WP-CLI inside the container stays available as well.

## Purpose

The goal of this deployment is to provide a production-ready, scalable WordPress instance with multisite capabilities and enhanced performance. By automating the custom image build and configuration processes via Docker Compose and Ansible, it minimizes manual intervention, reduces errors, and allows you to concentrate on building great content.

## Multisite

WordPress Multisite is opt-in. Set `services.wordpress.multisite.enabled: true` in the inventory to convert the deployed instance into a sub-domain Multisite network. Every entry in `domains.canonical` becomes the site of exactly that domain in the network; the first entry is the network primary, subsequent entries are child sites. [files/php/multisite/sites.php](files/php/multisite/sites.php) creates them and moves a site that an earlier deploy created at `<domain>.<network domain>` to `<domain>`.

RBAC under Multisite uses the hierarchical Keycloak group path:

- Per-site role: `/roles/web-app-wordpress/<canonical-domain>/<role>`
- Network-wide super-admin: `/roles/web-app-wordpress/network-administrator`

The Multisite variant in [meta/variants.yml](meta/variants.yml) sets `rbac.tenancy.axis: domain`, declares `network-administrator` with `scope: global` and keeps `mcp` global. [rbac_group_map.json.j2](templates/rbac_group_map.json.j2) builds every group path with `rbac_group_path` and hands the map to the mu-plugin as `WORDPRESS_RBAC_GROUP_MAP`.

Operator-facing instructions for assigning these groups live in [Administration RBAC](../../docs/administration/configuration/rbac.md). The design contract is in [RBAC design](../../docs/contributing/design/iam/rbac.md).

## Addons

Every plugin and mu-plugin is declared in `meta/addons/` under
the unified addon contract. The OIDC and WP-Discourse runtime config lives in each addon's `config:` block. Both install paths read those declarations: a `required` addon that fails to install stops the deploy, an optional one warns and is skipped.

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `daggerhart-openid-connect-generic` | `plugin` | enabled with the `sso` login method, which follows the `sso` service | `sso` → `web-app-keycloak` |
| `wp-discourse` | `plugin` | enabled with the `discourse` service | `discourse` → `web-app-discourse` |
| `activitypub` | `plugin` | enabled in variant 0 (Fediverse federation); off in later variants | none |
| `infinito-oidc-rbac-mapper` | `mu_plugin` | `required` (always installed, vendored) | `sso` → `web-app-keycloak` |
| `infinito-http-ca-trust` | `mu_plugin` | `required` (always installed, vendored) | none |
| `s3-uploads` | `plugin` | enabled with the `seaweedfs` service | none |
| `infinito-s3-uploads` | `mu_plugin` | enabled with the `seaweedfs` service | none |

The OIDC login + RBAC paths are covered by `test-admin-oidc-login.js` /
`test-rbac-roles.js` / `test-multisite-rbac.js`, the profile sync by `test-profile-sync.js`, the profile lock with its warning on `profile.php` and `user-edit.php` and against direct form, REST and XML-RPC writes by `test-profile-lock.js`, the Discourse round-trip by `test-discourse-roundtrip.js`.

## Playwright service dependencies

The Playwright suite in [files/playwright/playwright.spec.js](files/playwright/playwright.spec.js) gates its scenarios on the following shared services. Scenarios that depend on a service report as `skipped` when the corresponding `<SERVICE>_SERVICE_ENABLED=false` in the staged `.env`:

- `oidc`: baseline admin OIDC round-trip, the three Single-Site RBAC scenarios (subscriber/editor/administrator), the Multisite scenarios (bootstrap super-admin kept, network-administrator grant and revoke, per-site Editor on the primary and on a child site only) and the profile sync and read-only scenario.
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
