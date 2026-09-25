# LAM

## Description

Elevate your LDAP directory management with LAM (LDAP Account Manager), a powerful solution for administering LDAP directories. LAM offers an intuitive web interface for managing users, groups, and other LDAP objects, making directory operations both efficient and secure.

## Overview

This role deploys LAM in a Docker environment and integrates it with an NGINX reverse proxy to provide secure access. It leverages environment variable templates to configure LDAP connection settings and administrative credentials, ensuring a smooth and customizable installation of LDAP Account Manager.

## Features

- **User-Friendly Interface:** Easily manage LDAP directories through an intuitive web-app-based interface.
- **Customizable Deployment:** Configure LDAP settings and LAM’s administrative credentials via flexible environment variables.
- **Secure Access:** Utilize NGINX reverse proxy integration to safeguard your management interface.
- **Efficient Administration:** Streamline the handling of LDAP objects such as users, groups, and organizational units.

## Further Resources

- [LDAP Account Manager Official Website](https://www.ldap-account-manager.org/)

## Persona contract opt-outs

[`meta/services.yml`](./meta/services.yml) admits only the `web-app-lam` administrator RBAC group to the oauth2-proxy (`sso.oauth2.allowed_groups`), and `biber` carries an empty role list in the development inventory. The proxy denies `biber` before LAM is ever reached, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) declares `PERSONA_BIBER_BLOCKED=true`.

`PERSONA_ADMINISTRATOR_BLOCKED=true` is declared for a second, independent reason, and two separate obstacles justify it.

LAM's entry point is not `${APP_BASE_URL}/`. That path answers with a redirect to `/lam/`, whose body is nothing but `<meta http-equiv="refresh" content="0; URL=templates/login.php">`. The shared persona helper samples the DOM for a password field the moment its navigation settles, which is on that empty interstitial, and its fallback paths `/login`, `/admin/` and `/admin` all return 404 at the vhost root — so the login form is never reached. CI traces for the SSO-disabled variants confirm the helper issues no form submission at all, and LAM's own access log records no POST.

Behind that sits a second, smaller mismatch. LAM authenticates by binding an LDAP DN from its `Admins` list, which [`templates/env.j2`](./templates/env.j2) fills with `LDAP.DN.ADMINISTRATOR.DATA` and `LDAP.BIND_CREDENTIAL` — the `svc-db-openldap` `credentials.administrator_database_password` — while the shared helper types `lookup('users', 'administrator').password`, the secret of `uid=administrator,ou=users,…`, a different directory entry. That one is configurable rather than structural: the helper reads `ADMIN_NATIVE_PASSWORD` for exactly this case, and the role could render it. It is recorded here so the opt-out can be revisited together with the entry-point problem, which is the blocking one.

In the SSO-enabled variant the Keycloak round trip satisfies the oauth2-proxy but leaves LAM itself signed out, so the persona lands back on LAM's own login form and finds no logout control there.

The `guest` persona and the role-local reachability, TLS and HSTS assertions run unconditionally.
