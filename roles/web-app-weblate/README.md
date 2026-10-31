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

## Administration

The container's entrypoint provisions the administrator as the Weblate user `admin`; `WEBLATE_ADMIN_NAME` is its display name only. The role reads that account's API token out of Weblate's own database after the deploy and writes it to `sys-token-store` under `administrator` / `web-app-weblate`.

## Networks

Weblate is served on clearnet over https and on its onion sibling over plain http, from one container. Upstream builds every absolute URL, including the OIDC `redirect_uri`, from `SITE_URL`. [`files/python/settings_override.py`](files/python/settings_override.py) is mounted at `/app/data/settings-override.py`, the file upstream's `settings_docker.py` execs last. It replaces `weblate.middleware.ProxyMiddleware` and `weblate.accounts.strategy.WeblateStrategy` with the subclasses in [`files/python/weblate_network_middleware.py`](files/python/weblate_network_middleware.py) and [`files/python/weblate_network_strategy.py`](files/python/weblate_network_strategy.py), which take scheme and host from the request. They live in two modules because `social_django.utils` imports the strategy at app-ready time, before it defines the `load_strategy` that `weblate.middleware` imports back. The strategy module therefore imports nothing beyond `weblate.accounts.strategy`. The host is validated against `WEBLATE_ALLOWED_HOSTS`, which lists every network sibling, the internal service name and the loopback names. The override also turns off `SECURE_SSL_REDIRECT` and `SOCIAL_AUTH_REDIRECT_IS_HTTPS`, because the proxy already redirects clearnet http to https. It sets the language cookie to `SameSite=Lax`.

The subclasses override upstream internals checked against Weblate `2026.9` (`weblate/middleware.py` `ProxyMiddleware.process_request`, `weblate/accounts/strategy.py` `WeblateStrategy.build_absolute_uri`/`request_is_secure`/`request_host`/`request_port`). Re-check both before raising `services.weblate.version`. The override refuses to start Weblate when either upstream class path is gone.

WebAuthn second factors stay bound to the clearnet domain (`OTP_WEBAUTHN_*` follows `SITE_URL`), and a plain-http onion page is no secure context, so a WebAuthn key cannot be used on the onion sibling. E-mails, feeds and other links Weblate renders from `SITE_URL` keep naming the clearnet domain.

## Further resources

- [Weblate documentation](https://docs.weblate.org/)
- [The translation gateway that reads this memory](../web-svc-translate/)
