# FusionDirectory

> **End of life.** Infinito.Nexus neither maintains nor tests this role, and the
> default `INFINITO_LIFECYCLES` envelope keeps it out of every CI round. Deploy it
> at your own risk and take support from
> [upstream FusionDirectory](https://www.fusiondirectory.org/).

## Description

[FusionDirectory](https://www.fusiondirectory.org/) is a web-based LDAP administration tool that manages users, groups, and other directory objects through a pluggable interface. The application stores all of its data in an external LDAP directory, which makes it the natural front-end for the project's `svc-db-openldap` backend.

## Overview

This role deploys FusionDirectory on Docker Compose against the project's central `svc-db-openldap` server. The OIDC variant gates the FusionDirectory web UI through `web-app-keycloak`'s SSO-proxy sidecar for SSO; the LDAP variant relies on the same FusionDirectory binding to `svc-db-openldap` as its primary auth path. RBAC follows the LDAP group model that FusionDirectory already understands natively, so no glue layer is required for authorisation mapping.

## Features

- **LDAP-native administration:** Manage users, groups, and posix attributes directly against `svc-db-openldap`.
- **Containerized deployment:** Run FusionDirectory through Docker Compose with the project's standard role-meta wiring.
- **Native OIDC SSO via SSO-proxy sidecar:** Gate the FusionDirectory web UI through the project's SSO-proxy sidecar (provided by `web-app-keycloak`) for OIDC-authenticated entry.
- **Front-proxy integration:** Publish the app through `svc-stack` for TLS termination and per-domain routing.
- **Single sign-on through the proxy header:** with the oauth2-proxy gate active, `files/shell/ldap/bootstrap.sh` sets `fdLoginMethod: LoginHTTPHeader` and reads the user name from the `X-Forwarded-Preferred-Username` header that the vhost always overwrites from the oauth2-proxy identity. Without the gate it sets `LoginPost`, so FusionDirectory shows its own login form. Both values are reconciled on every deploy.
- **Identity header bound to the front proxy:** the vhost sends the `sso_proxy_secret` credential as `X-Infinito-Sso-Proxy` with every request, and a `server-begin` fragment mounted into the image's nginx (`templates/sso_proxy.conf.j2`) answers 403 to every request that carries `X-Forwarded-Preferred-Username` without that secret. A client that reaches the container port, the oauth2-proxy port or the role network directly can no longer sign in as another user. `files/test/test.sh` asserts the refusal inside the container on every CLI test run.
- **RBAC through ACL roles:** every deploy creates the ACL roles `admin`, `user-manager` and `self-service` under `ou=aclroles` and assigns them on the base DN to the matching RBAC groups `web-app-fusiondirectory-administrator`, `-user-manager` and `-self-service` in the roles OU. FusionDirectory resolves the `member` attribute of these `groupOfNames` entries. The platform administrator persona keeps its direct `admin` grant.
- **Login recovery:** when the header login fails, deploy with the `sso` service disabled, or replace `fdLoginMethod` of `cn=config,ou=fusiondirectory,<base DN>` with `LoginPost`, to get the login form back.

## LDAP coverage

[`meta/services.yml`](./meta/services.yml) pins `ldap.enabled` to `true`, because FusionDirectory is the admin UI of the `svc-db-openldap` directory, so every sign-in at its own login form is the LDAP bind. With `sso` off, [`files/playwright/test-design.js`](./files/playwright/test-design.js) signs the administrator in through that form, and [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) signs `biber` in through it once per role group. The administrator scenario carries no `ldap` gate, because no variant turns the directory off.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [FusionDirectory Official Website](https://www.fusiondirectory.org/)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/6NrqqPZvjikvPNNoJWsSru)

## Persona contract opt-outs

The shared `biber` and `administrator` persona journeys are opted out via `PERSONA_BIBER_BLOCKED` / `PERSONA_ADMINISTRATOR_BLOCKED` in `templates/playwright.env.j2`.
`biber` holds no FusionDirectory role, so the oauth2-proxy denies it. [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) asserts that denial and adds `biber` to each role group in turn to assert the rights of the matching ACL role.
The shared admin flow has not been verified against the header login. [`files/playwright/test-design.js`](./files/playwright/test-design.js) asserts the administrator's sign-in and rights in both variants, and [`files/playwright/playwright.spec.js`](./files/playwright/playwright.spec.js) asserts that the Keycloak sign-in lands in FusionDirectory without a second login form.
