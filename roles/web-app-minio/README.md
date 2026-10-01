# MinIO

## Description

**MinIO** is an S3-compatible object storage service for files, media, backups, and AI artifacts, self-hosted for performance and control.

## Overview

Applications that speak “S3” (Pixelfed, Mastodon, Nextcloud, Flowise, etc.) store and retrieve objects from MinIO buckets using familiar SDKs and CLIs. Admins manage buckets, users, and access policies through a browser console while keeping everything on-prem.

## Features

* S3-compatible API for broad app compatibility
* Buckets, users, access keys, and fine-grained policies
* Optional versioning, lifecycle rules, and object lock
* Presigned URLs for secure, time-limited uploads/downloads
* Ideal for AI stacks: datasets, embeddings, and artifacts

## Further Resources

* MinIO: [www.min.io](https://www.min.io)
* AWS S3 (API background): [aws.amazon.com/s3](https://aws.amazon.com/s3)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2` for two different reasons. The MinIO Console version pinned here never renders an SSO button — `/api/v1/login` answers `redirectRules: null` however the identity provider is registered server-side — so there is no in-page OIDC entry point for the shared helper to click. Biber is blocked because the only MinIO policy the role creates is the administrator RBAC group path (`MINIO_OIDC_POLICY_NAME` in `vars/main.yml`, attached in `tasks/02_ldap.yml`) and MinIO has no self-service signup, so biber maps to no policy and has no authenticated surface at either tier.

The administrator journey is covered bespoke in `files/playwright/playwright.spec.js`: the integrated OIDC path is proven at the STS `AssumeRoleWithWebIdentity` tier, and the LDAP variant additionally drives the Console form login and logout. The path back to the generic administrator persona is a Console build that surfaces the configured IdP on its login form.
