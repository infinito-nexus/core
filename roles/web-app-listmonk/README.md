# Listmonk

## Description

Elevate your email marketing with Listmonk, a high-performance, self-hosted newsletter and mailing list manager featuring a modern, intuitive dashboard. Listmonk empowers you with advanced analytics, efficient subscriber segmentation, and streamlined campaign management, all configurable via a flexible TOML configuration file.

## Overview

This role deploys Listmonk using Docker, ensuring a robust and scalable setup for your newsletter management needs. Listmonk’s architecture supports a dedicated PostgreSQL database and integration with an NGINX reverse proxy for secure access. To configure and manage your instance, use the provided configuration files:

- [Installation.md](./Installation.md)
- [Upgrade.md](./Upgrade.md)

## Features

- **High Performance:** Optimized for handling large-scale mailing lists and newsletters with rapid processing.
- **Modern Dashboard:** Enjoy a sleek, user-friendly interface for managing campaigns and analyzing performance.
- **Advanced Analytics:** Gain insights through detailed reporting on campaign metrics and subscriber behavior.
- **Flexible Configuration:** Easily customize settings such as database connections, admin credentials, and server configurations via a TOML file.
- **Robust Infrastructure:** Seamlessly integrates with PostgreSQL for reliable data management and supports deployment behind a reverse proxy.
- **Restricted SSO access:** With SSO enabled, `security.oidc.auto_create_users` stays off and [files/sql/rbac_reconcile.sql](./files/sql/rbac_reconcile.sql) provisions Listmonk accounts only for the `web-app-listmonk` `administrator` (Super Admin), `manager` and `viewer` members, matched by email. The `manager` and `viewer` user roles are created with their permission sets from `LISTMONK_RBAC_ROLES`. Every other account of type `user` is disabled, API accounts stay untouched, and the platform administrator stays Super Admin. The script runs through `psql` in the database container as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer, so a group change reaches Listmonk within one timer interval.
- **Login Methods:** `services.listmonk.login.method.*` in [meta/services.yml](./meta/services.yml) drives [vars/main.yml](./vars/main.yml) and [tasks/02_manager_ops.yml](./tasks/02_manager_ops.yml). `sso` sets `security.oidc.enabled` (the setting is written while the `sso` service is on). `native` sets the administrator's `password_login`; the accounts the RBAC hook creates never get one. Listmonk renders its password form unconditionally, so while `sso` is the only method [files/javascript/oidc-autologin.js](./files/javascript/oidc-autologin.js), stored as `appearance.public.custom_js`, hides the password form and the reset link and submits the OIDC form; otherwise the setting is emptied. `2fa` is Listmonk's TOTP, which it offers exactly to accounts with `password_login` and cannot switch on its own, so the deploy refuses a `2fa` flag that differs from `native`. Listmonk has no setting that requires the second factor, so `login.method.2fa.enforced` only offers it here and each account enrolls on its own. Listmonk has no LDAP path, self-registration, passkey or magic link here, so the role declares none of them.
- **Break-Glass:** With SSO on the administrator has no password login, so the break-glass path is the CLI: set `password_login` of the administrator through `psql` in the database container, the way [tasks/02_manager_ops.yml](./tasks/02_manager_ops.yml) does, and sign in at `/admin/login` with JavaScript disabled, because the script hides the form. API users keep their tokens in every mode.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [Listmonk Official Website](https://listmonk.app/)
- [Listmonk Installation Documentation](https://listmonk.app/docs/installation/)
- [Listmonk GitHub Repository](https://github.com/knadh/listmonk/)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/XHHFGfbzxtd6JxuRDB31vy)
