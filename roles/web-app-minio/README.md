# MinIO

> **End of life.** Infinito.Nexus neither maintains nor tests this role, and the default `INFINITO_LIFECYCLES` envelope keeps it out of every CI round. Deploy it at your own risk and take support from [www.min.io](https://www.min.io).

## Description

**MinIO** is an S3-compatible object storage service for files, media, backups, and AI artifacts, self-hosted for performance and control.

## Overview

Applications that speak “S3” (Pixelfed, Mastodon, Nextcloud, Flowise, etc.) store and retrieve objects from MinIO buckets using familiar SDKs and CLIs. Admins manage buckets, users, and access policies through a browser console while keeping everything on-prem.

## Features

- S3-compatible API for broad app compatibility
- Buckets, users, access keys, and fine-grained policies
- Optional versioning, lifecycle rules, and object lock
- Presigned URLs for secure, time-limited uploads/downloads
- Ideal for AI stacks: datasets, embeddings, and artifacts
- **RBAC policies:** One MinIO policy per RBAC group path (`administrator`, `readwrite`, `readonly`). OIDC logins pick them up through the groups claim, and the LDAP variant attaches each policy to its `web-app-minio-<role>` group under the roles OU.
- **Login methods:** `services.minio.login.method.<method>.enabled` in [meta/services.yml](./meta/services.yml) declares `sso`, `ldap` and `native`. `sso` registers Keycloak as the named OpenID IdP ([tasks/01_oidc.yml](./tasks/01_oidc.yml)), which serves the STS `AssumeRoleWithWebIdentity` tier. `ldap` renders the `MINIO_IDENTITY_LDAP_*` settings ([templates/env.j2](./templates/env.j2)) and binds the policies to the LDAP role groups ([tasks/02_ldap.yml](./tasks/02_ldap.yml)), so with SSO on an LDAP account signs in through Keycloak's LDAP federation instead. `native` has no MinIO switch: the root account (`MINIO_ROOT_USER`) always signs in through the Console form, and the Console form is shared between root and LDAP accounts. The pinned Console renders no SSO entry, so the role keeps that form visible in every mode. Break-glass: the root account through the Console form at `/login`, or `mc` with the root credentials.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- MinIO: [www.min.io](https://www.min.io)
- AWS S3 (API background): [aws.amazon.com/s3](https://aws.amazon.com/s3)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2` for two different reasons. The MinIO Console version pinned here never renders an SSO button — `/api/v1/login` answers `redirectRules: null` however the identity provider is registered server-side — so there is no in-page OIDC entry point for the shared helper to click. Biber is blocked because MinIO policies exist only for the RBAC group paths (`MINIO_RBAC_POLICIES` in `vars/main.yml`) and MinIO has no self-service signup, so biber without one of those groups maps to no policy and has no authenticated surface at either tier.

The administrator journey is covered bespoke in `files/playwright/playwright.spec.js`: the integrated OIDC path is proven at the STS `AssumeRoleWithWebIdentity` tier, and the LDAP variant additionally drives the Console form login and logout. The path back to the generic administrator persona is a Console build that surfaces the configured IdP on its login form.
