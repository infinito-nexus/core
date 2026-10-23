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

## Further resources

- [Weblate documentation](https://docs.weblate.org/)
- [The translation gateway that reads this memory](../web-svc-translate/)
