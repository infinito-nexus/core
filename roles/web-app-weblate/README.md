# Weblate

## Description

[Weblate](https://weblate.org) is a web-based continuous localization platform. It keeps a translation memory, glossaries and a review workflow, so a human translation can be written once, approved, and reused everywhere.

## Overview

In this deployment Weblate is the memory behind the translation gateway. [`web-svc-translate`](../web-svc-translate/) asks Weblate first: a string with an approved translation is returned verbatim and no engine is called. Translators reach Weblate's own UI at `web.translate.{{ DOMAIN_PRIMARY }}`, through Keycloak when SSO is deployed.

## Features

- **Translation memory:** every approved string is reusable by the gateway and by other components.
- **Glossaries:** terms that must survive a translation; the gateway rejects a machine answer that drops one.
- **Review workflow:** a translation becomes authoritative when a reviewer approves it.
- **API access:** the deploy reads the API token Weblate issued for its administrator and persists it in the token store, where the gateway reads it.
- **Role groups:** members of the `administrator` role group are superusers, members of `reviewer` join the built-in Reviewers team and members of `manager` the built-in Managers team; every other account loses the flag and both teams. [files/python/rbac_reconcile.py](./files/python/rbac_reconcile.py) runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer; the platform administrator, bots and the anonymous account are never changed, and an account the OIDC sign-in creates is converged on the next run.

## Login methods

`services.weblate.login.method` declares `sso`, `native`, `2fa` and `registration` (see [Login Methods](../../docs/contributing/design/iam/login.md)), and [templates/env.j2](./templates/env.j2) maps them onto Weblate's settings:

- `sso` renders the `WEBLATE_SOCIAL_AUTH_OIDC_*` backend; `WEBLATE_REGISTRATION_ALLOW_BACKENDS=oidc` lets a Keycloak sign-in create its account while local registration is closed.
- `native` off sets `WEBLATE_NO_EMAIL_AUTH=1`, which removes the e-mail and password form, so with SSO on the sign-in offers Keycloak only.
- `registration` drives `WEBLATE_REGISTRATION_OPEN` and, with SSO on, adds `email` to the allowed registration backends.
- `2fa` covers Weblate's own second factor (TOTP, WebAuthn security keys, recovery codes through `django_otp`), which the pinned image enables unconditionally and offers no setting for. While `2fa` is off, the `javascript` service of [meta/services.yml](./meta/services.yml) is on and injects [templates/javascript.js.j2](./templates/javascript.js.j2), which hides the enrollment entries under `/accounts/auth/tokens/` in the account settings. Accounts that already enrolled keep their second factor at sign-in; nothing is enforced.

## Administration

The container's entrypoint provisions the administrator as the Weblate user `admin`; `WEBLATE_ADMIN_NAME` is its display name only. The role reads that account's API token out of Weblate's own database after the deploy and writes it to `sys-token-store` under `administrator` / `web-app-weblate`.

Break-glass access while SSO is on: the administrator's API token (`Authorization: Token <token>` against `/api/`), which `files/playwright/playwright.spec.js` proves on every run, and `weblate` management commands (`createadmin`, `changepassword`) inside the container.

## Further resources

- [Weblate documentation](https://docs.weblate.org/)
- [The translation gateway that reads this memory](../web-svc-translate/)
