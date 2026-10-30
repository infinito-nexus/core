# Decidim

## Description

Deploys [Decidim](https://decidim.org/) (a free, open-source participatory democracy platform) as part of the Infinito.Nexus stack.

## Overview

This role deploy Decidim, an open-source participatory democracy platform for public consultations, civic processes, community voting, and collaborative policy creation.

## Features

- Custom Docker image built on `ghcr.io/decidim/decidim` with OpenID Connect support
- PostgreSQL database via the shared platform instance
- Redis for caching and Action Cable
- OIDC SSO via Keycloak using `omniauth_openid_connect`
- **Role Groups:** Every OIDC registration and login sets `admin` from the `administrator` role group and the `user_manager` role from the `user-manager` role group ([files/ruby/initializers/infinito_rbac.rb](./files/ruby/initializers/infinito_rbac.rb)). Only accounts with an OIDC identity change; the administrator the deploy seeds keeps its rights.
- Accessible at `https://decidim.<your-domain>`
- **Login methods:** `services.decidim.login.method` declares `sso`, `native` and `registration`. `sso` sets the organization's `omniauth_settings_openid_connect_enabled` ([files/ruby/configure_oidc.rb](./files/ruby/configure_oidc.rb)), which shows or hides the OpenID Connect entry. `native` and `registration` set the organization's `users_registration_mode` ([files/ruby/ensure/registration_mode.rb](./files/ruby/ensure/registration_mode.rb)): `enabled` with both on, `existing` (local sign-in without sign-up) with `native` alone, and `disabled` (external accounts only, no password form, no password reset, no sign-up) with `native` off. Decidim has no LDAP or second factor of its own, and Keycloak accounts keep registering through OpenID Connect in every mode.
- **Break-glass path:** `disabled` also refuses the password login on the server, so with SSO on the seeded administrator signs in through Keycloak by e-mail. When Keycloak is unavailable, set `users_registration_mode` back to `existing` with `bundle exec rails runner 'Decidim::Organization.first.update!(users_registration_mode: :existing)'` inside the Decidim container, or redeploy with `applications.web-app-decidim.services.decidim.login.method.native.enabled: true`; the administrator then signs in at `/users/sign_in` with its e-mail address and password.

## SSO / Authentication

Decidim's base image does not include an OpenID Connect OmniAuth strategy. This role builds a custom image that:

- Installs the `omniauth_openid_connect` gem via Bundler
- Patches decidim-core's `omniauth.rb` initializer to register the provider gated on `ENV["OIDC_ENABLED"]` (Rails 7.2 no longer uses `config/secrets.yml`)
- Patches decidim-core's `omniauth_helper.rb` to return the correct icon

Credentials (`OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_ISSUER`) are read from env vars at runtime (never stored in the database) to avoid `ActiveSupport::MessageEncryptor::InvalidMessage` errors on container rebuild.

To enable SSO, set `services.sso.enabled: true` in your inventory.

## Configuration

Key settings in `meta/services.yml` and `meta/server.yml`:

| Key | Default | Description |
|-----|---------|-------------|
| `services.sso.enabled` | `true` | Enable Keycloak SSO via OpenID Connect |
| `services.postgres.shared` | `true` | Use the shared PostgreSQL service |
| `domains.canonical` | `decidim.{{ DOMAIN_PRIMARY }}` | Public domain |

## Further Resources

- [Decidim documentation](https://docs.decidim.org/)
- [Decidim Docker image](https://ghcr.io/decidim/decidim)
- [omniauth_openid_connect](https://github.com/omniauth/omniauth_openid_connect)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/4MNz31wg3FuRvYoGMmbKxV)

## Persona contract opt-outs

Both authenticated Playwright personas are blocked, and both are covered by bespoke tests in `files/playwright/playwright.spec.js` instead.

The `administrator` persona is blocked because Decidim's admin is a Devise account seeded by `files/ruby/ensure_admin_user.rb` and Devise signs in by e-mail address. The role's Playwright env therefore exposes `ADMIN_EMAIL` and no `ADMIN_USERNAME`, which is the variable the shared admin helper reads.

The `biber` persona logs in through OIDC without trouble; what it cannot do is log out. Decidim's sign-out is a `data-method` link inside the account dropdown, so the role's own tests navigate to `/users/sign_out` directly rather than clicking a button the shared helper could find.
