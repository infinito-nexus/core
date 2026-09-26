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
- Accessible at `https://decidim.<your-domain>`

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

## References

- [Decidim documentation](https://docs.decidim.org/)
- [Decidim Docker image](https://ghcr.io/decidim/decidim)
- [omniauth_openid_connect](https://github.com/omniauth/omniauth_openid_connect)

## Persona contract opt-outs

Both authenticated Playwright personas are blocked, and both are covered by bespoke tests in `files/playwright/playwright.spec.js` instead.

The `administrator` persona is blocked because Decidim's admin is a Devise account seeded by `files/ruby/ensure_admin_user.rb` and Devise signs in by e-mail address. The role's Playwright env therefore exposes `ADMIN_EMAIL` and no `ADMIN_USERNAME`, which is the variable the shared admin helper reads.

The `biber` persona logs in through OIDC without trouble; what it cannot do is log out. Decidim's sign-out is a `data-method` link inside the account dropdown, so the role's own tests navigate to `/users/sign_out` directly rather than clicking a button the shared helper could find.
