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
- **Directory login:** LAM signs users in with "LDAP search": it looks up the typed user name under the users OU, admits only members of the `web-app-lam` administrator RBAC group, and binds as that user. `files/shell/entrypoint.sh` writes the search suffix and filter from `templates/env.j2` into the profile on every fresh container.
- **Group-based write access:** members of the `web-app-lam` administrator group edit directory entries through the `svc-db-openldap` ACL, `userPassword` included, so they set and reset the passwords of other accounts with "Set password". `svc-db-openldap` applies the ACL to an existing directory on its next deploy.
- **Login recovery:** the profile keeps the LDAP root DN in its `Admins` list. When the search login fails, sign in to the LAM configuration editor with the LAM master password and switch the login method of the `lam` profile back to "Fixed list".

## Further Resources

- [LDAP Account Manager Official Website](https://www.ldap-account-manager.org/)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/E9doW8UWynLbGQFEfuhREo)

## Persona contract opt-outs

[`meta/services.yml`](./meta/services.yml) admits only the `web-app-lam` administrator RBAC group to the oauth2-proxy (`sso.oauth2.allowed_groups`), and `biber` carries an empty role list in the development inventory. The proxy denies `biber` before LAM is ever reached, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) declares `PERSONA_BIBER_BLOCKED=true`.

`PERSONA_ADMINISTRATOR_BLOCKED=true` is declared for a second, independent reason, and two separate obstacles justify it.

LAM's entry point is not `${APP_BASE_URL}/`. That path answers with a redirect to `/lam/`, whose body is nothing but `<meta http-equiv="refresh" content="0; URL=templates/login.php">`. The shared persona helper samples the DOM for a password field the moment its navigation settles, which is on that empty interstitial, and its fallback paths `/login`, `/admin/` and `/admin` all return 404 at the vhost root — so the login form is never reached. CI traces for the SSO-disabled variants confirm the helper issues no form submission at all, and LAM's own access log records no POST.

LAM's search login accepts the platform administrator's user name and `lookup('users', 'platform_administrator').password`, the same pair the shared helper types. [`files/playwright/test-directory-login.js`](./files/playwright/test-directory-login.js) asserts that login, the group filter and the write access directly.

In the SSO-enabled variant the Keycloak round trip satisfies the oauth2-proxy but leaves LAM itself signed out, so the persona lands back on LAM's own login form and finds no logout control there.

The `guest` persona and the role-local reachability, TLS and HSTS assertions run unconditionally.
