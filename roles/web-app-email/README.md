# Email

## Description

`web-app-email` stands for "the mail server" of a deployment. Consumers depend on it instead of on a concrete mail server: they declare `services.email` gated on `'web-app-email' in group_names` and list `web-app-email` under `run_after`.

## Overview

The role is a thin wrapper with no containers, domains or surface of its own. It dispatches to the mail provider role it selects, which deploys with its own `application_id` and configuration.

## Features

- **Provider indirection:** Consumers reference `web-app-email` instead of a concrete mail server, so the provider changes without touching any consumer.
- **Single point of truth:** `email.provider` in [`meta/services.yml`](./meta/services.yml) selects the provider; `MAIL_PROVIDER` and the `mail_provider` and `email` lookups derive from it.
- **Ordering:** `email.run_after` places the wrapper after its provider, so every consumer that runs after the wrapper also runs after the provider.
- **Inventory guard:** The inventory validator rejects an inventory that deploys a mail provider without the wrapper.

## Provider selection

[`meta/services.yml`](./meta/services.yml) is the single point of truth for the provider:

| Key | Meaning |
|---|---|
| `email.provider` | Role id of the mail provider. `MAIL_PROVIDER` and the `mail_provider` and `email` lookups derive from it. |
| `email.run_after` | Orders the wrapper after its provider, so every consumer that runs after the wrapper also runs after the provider. |
| `<provider entity>` | The service block that pulls the provider into the inventory and makes the service loader preload it. |

The default provider is [Stalwart](../web-app-stalwart/), and both variants in [`meta/variants.yml`](./meta/variants.yml) deploy it. An inventory selects another provider only by overriding `applications.web-app-email.services.email.provider` and adding that role to its groups; the operator then owns the result.

## Upgrading an existing inventory

An inventory that predates this role lists only the provider group. Add `web-app-email` to the same hosts before the next deploy, or every consumer deploys with mail switched off. The inventory validator rejects a provider without the wrapper; see [Upgrading an existing inventory](../../docs/administration/configuration/email.md#upgrading-an-existing-inventory-) for the full note.

Every provider declares an `email` service block on `web-app-email`, so a deploy that names only the provider still pulls the wrapper in.

## Adding a provider

A new mail server becomes selectable without touching any consumer:

1. Add the provider role and let its primary entity declare `covers: [email]`, which marks it as a mail provider.
2. Point `email.provider`, `email.run_after` and the provider service block of this role at it.

Every covering role that is not the selected provider counts as inactive: it publishes no onion ports and shares its host mail ports with the selected one.

[`test_mail_provider_reference.py`](../../tests/lint/ansible/services/test_mail_provider_reference.py) keeps every other role off the concrete provider ids and keeps the three keys of step 2 in agreement.
