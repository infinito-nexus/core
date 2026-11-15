# pgAdmin

## Description

pgAdmin is the most popular and feature‑rich open source administration and development platform for PostgreSQL. This deployment provides a secure, containerized pgAdmin instance complete with optional OAuth2 proxy support for enhanced authentication. It is built for both developers and database administrators who want an easy‐to‐use web interface to manage multiple PostgreSQL servers.

## Overview

This Docker Compose deployment uses Ansible automation to launch pgAdmin together with necessary network and volume configurations. It enables you to centrally manage your PostgreSQL databases with the following core software features:

- **Intuitive Web UI:**  
  Access a modern, responsive, and highly customizable dashboard to manage your PostgreSQL servers.
  
- **Multi‑Server Management:**  
  Connect to and administer multiple PostgreSQL instances from a single interface.
  
- **Optional OAuth2 Integration:**  
  Secure your pgAdmin access by integrating an external OAuth2 provider.
  
- **Robust Connectivity:**  
  Easily manage database configurations, user accounts, and monitor query activity with built‑in health checks.

- **Flexible Configuration:**  
  Adjust settings such as SSL options, port numbers, and server credentials through environment variables and templated configuration files.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.
- **Native Keycloak OAuth2:** With SSO the login page offers pgAdmin's own OAuth2 button only (`AUTHENTICATION_SOURCES = ['oauth2']`, see Login methods below). The username comes from the OIDC username claim, accounts are created on first login, and `OAUTH2_ADDITIONAL_CLAIMS` admits only members of the `administrator` and `user` role groups.
- **Role reconcile:** With SSO, [files/python/reconcile_oauth2_roles.py](./files/python/reconcile_oauth2_roles.py) gives each `administrator` group member an OAuth2 account with the Administrator role and sets every other OAuth2 account to User. It runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer. The internal default administrator stays untouched.
- **Login methods:** `services.pgadmin.login.method.<method>.enabled` in [meta/services.yml](./meta/services.yml) declares `sso`, `native` and `2fa`. `sso` adds `oauth2` and `native` adds `internal` to `PGADMIN_CONFIG_AUTHENTICATION_SOURCES` (`PGADMIN_AUTHENTICATION_SOURCES` in [vars/main.yml](./vars/main.yml)); pgAdmin hides the email and password form, the forgotten-password link and the Login button whenever `internal` is missing and refuses an internal sign-in server-side. `2fa` sets `PGADMIN_CONFIG_MFA_ENABLED`, which offers the email and authenticator second factor for enrollment, and `login.method.2fa.enforced` (default `true`) sets `PGADMIN_CONFIG_MFA_FORCE_REGISTRATION`, which makes an account without a second factor register one at its next sign-in. Variant 1 keeps the enforcement on, so [test-2fa-enrollment.js](./files/playwright/test-2fa-enrollment.js) proves that the administrator's internal sign-in ends on the MFA registration and that the browser sends it back there; nothing else signs a local account in that round. pgAdmin has no self-registration. Break-glass: with SSO on the internal administrator (`PGADMIN_DEFAULT_EMAIL`) has no web sign-in, so the path is the CLI inside the container, `/venv/bin/python3 /pgadmin4/setup.py update-external-user <username> --auth-source oauth2 --admin` to promote an OAuth2 account, or setting `applications.web-app-pgadmin.services.pgadmin.login.method.native.enabled: true` and redeploying to bring the internal form back.
- **Saved server passwords:** OAuth2 accounts keep no pgAdmin password, so pgAdmin asks them for a master password before it stores a server password (`MASTER_PASSWORD_REQUIRED`).

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [pgAdmin Official Homepage](https://www.pgadmin.org/)
- [pgAdmin Documentation](https://www.pgadmin.org/docs/)
- [Corporate design review: screenshots in light, dark and desktop](https://claude.ai/artifact/QvGNAugdfpWe5Ed7SqeDRX)

## Persona contract opt-outs

With SSO the administrator signs in through pgAdmin's own OAuth2 button, and [`files/playwright/test-rbac-roles.js`](./files/playwright/test-rbac-roles.js) drives that journey; without SSO pgAdmin's only login id is the internal e-mail `PGADMIN_DEFAULT_EMAIL` ([`templates/env.j2`](./templates/env.j2), [`vars/main.yml`](./vars/main.yml)), not the Keycloak username. `OAUTH2_ADDITIONAL_CLAIMS` admits only the `administrator` and `user` RBAC groups, and `biber` carries an empty role list, so pgAdmin refuses it after the Keycloak login; the same spec asserts that refusal and the admission through the `user` group. [`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`; the `guest` persona and the baseline assertions run unconditionally.
