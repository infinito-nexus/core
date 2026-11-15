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

- `sso` renders the `WEBLATE_SOCIAL_AUTH_OIDC_*` backend; `WEBLATE_REGISTRATION_ALLOW_BACKENDS=oidc` lets a Keycloak sign-in create its account while local registration is closed. A sign-in reaches an existing account only through its `oidc` link keyed by the token's `sub`, never by e-mail: [files/python/settings_override.py](./files/python/settings_override.py), mounted at `/app/data/settings-override.py`, drops `associate_by_email` from the pipeline, and [files/python/adopt_admin.py](./files/python/adopt_admin.py) links the administrator to the Keycloak id that [roles/web-app-keycloak/tasks/utils/directory_users.yml](../web-app-keycloak/tasks/utils/directory_users.yml) reads at deploy.
- `native` off sets `WEBLATE_NO_EMAIL_AUTH=1`, which removes the e-mail and password form, so with SSO on the sign-in offers Keycloak only.
- `registration` drives `WEBLATE_REGISTRATION_OPEN` and, with SSO on, adds `email` to the allowed registration backends.
- `2fa` covers Weblate's own second factor (TOTP, WebAuthn security keys, recovery codes through `django_otp`), which the pinned image enables unconditionally and offers no setting for. While `2fa` is off, the `javascript` service of [meta/services.yml](./meta/services.yml) is on and injects [templates/javascript.js.j2](./templates/javascript.js.j2), which hides the enrollment entries under `/accounts/auth/tokens/` in the account settings; accounts that already enrolled keep their second factor at sign-in. Weblate has no site-wide switch, only `enforced_2fa` per team and per project, so `login.method.2fa.enforced` (default `true`, effective only with `2fa` on) reaches it through `WEBLATE_LOGIN_2FA_ENFORCED` in [templates/env.j2](./templates/env.j2) and [files/python/weblate_infinito/tasks.py](./files/python/weblate_infinito/tasks.py). The settings override installs that module as the Django app `weblate_infinito`; it runs at every deploy through [tasks/utils/two_factor.yml](./tasks/utils/two_factor.yml) and every hour as a Celery beat task, and flags every project and every team except `Guests` and the teams a project defines. A flagged team drops its permissions for every member without a second factor, bots included, so flagging a project's own teams would cut its project API tokens; the project's `enforced_2fa` covers their human members and spares bots. An account without a second factor sees Weblate's enrollment banner and loses what a flagged team grants and every permission on a flagged project, and Weblate refuses it edits there even as a superuser, the platform administrator included. Anonymous visitors keep browsing but lose the permission-checked actions of a flagged project, such as suggestions. The translation gateway's token only reads, which the superuser check still allows. Lifting the enforcement (`enforced: false` or `2fa` off) clears only the flags the deploy switched on, listed in `/app/data/infinito/enforced_2fa.json`; a flag an admin set stays. The SSO-off variant sets `enforced: false`, so its Playwright accounts keep their permissions without a second factor.

## Administration

The container's entrypoint provisions the administrator as the Weblate user `admin`; `WEBLATE_ADMIN_NAME` is its display name only. The role reads that account's API token out of Weblate's own database after the deploy and writes it to `sys-token-store` under `administrator` / `web-app-weblate`.

Break-glass access while SSO is on: the administrator's API token (`Authorization: Token <token>` against `/api/`), which `files/playwright/playwright.spec.js` proves on every run, and `weblate` management commands (`createadmin`, `changepassword`) inside the container.

## Networks

Weblate is served on clearnet over https and on its onion sibling over plain http, from one container. Upstream builds every absolute URL, including the OIDC `redirect_uri`, from `SITE_URL`. [`files/python/settings_override.py`](files/python/settings_override.py) is mounted at `/app/data/settings-override.py`, the file upstream's `settings_docker.py` execs last. It replaces `weblate.middleware.ProxyMiddleware` and `weblate.accounts.strategy.WeblateStrategy` with the subclasses in [`files/python/weblate_network/middleware.py`](files/python/weblate_network/middleware.py) and [`files/python/weblate_network/strategy.py`](files/python/weblate_network/strategy.py), mounted as the namespace package `weblate_network` under `/app/infinito`, which take scheme and host from the request. They live in two modules because `social_django.utils` imports the strategy at app-ready time, before it defines the `load_strategy` that `weblate.middleware` imports back. The strategy module therefore imports nothing beyond `weblate.accounts.strategy`. The host is validated against `WEBLATE_ALLOWED_HOSTS`, which lists every network sibling, the internal service name and the loopback names. The override also turns off `SECURE_SSL_REDIRECT` and `SOCIAL_AUTH_REDIRECT_IS_HTTPS`, because the proxy already redirects clearnet http to https. It sets the language cookie to `SameSite=Lax`.

The subclasses override upstream internals checked against Weblate `2026.9` (`weblate/middleware.py` `ProxyMiddleware.process_request`, `weblate/accounts/strategy.py` `WeblateStrategy.build_absolute_uri`/`request_is_secure`/`request_host`/`request_port`). Re-check both before raising `services.weblate.version`. The override refuses to start Weblate when either upstream class path is gone.

WebAuthn second factors stay bound to the clearnet domain (`OTP_WEBAUTHN_*` follows `SITE_URL`), and a plain-http onion page is no secure context, so a WebAuthn key cannot be used on the onion sibling. E-mails, feeds and other links Weblate renders from `SITE_URL` keep naming the clearnet domain.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further resources

- [Weblate documentation](https://docs.weblate.org/)
- [The translation gateway that reads this memory](../web-svc-translate/)
