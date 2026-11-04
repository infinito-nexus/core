# Email

## Description

`web-app-email` stands for "the mail server" of a deployment. Consumers depend on it instead of on a concrete mail server: they declare `services.email` gated on `'web-app-email' in group_names` and list `web-app-email` under `run_after`. The role itself is a thin wrapper with no containers, domains or surface of its own; it dispatches to the mail provider role it selects, which deploys with its own `application_id` and configuration.

## Provider selection

[`meta/services.yml`](./meta/services.yml) is the single point of truth for the provider:

| Key | Meaning |
|---|---|
| `email.provider` | Role id of the mail provider. `MAIL_PROVIDER` and the `mail_provider` and `email` lookups derive from it. |
| `email.run_after` | Orders the wrapper after its provider, so every consumer that runs after the wrapper also runs after the provider. |
| `<provider entity>` | The service block that pulls the provider into the inventory and makes the service loader preload it. |

The default provider is [Stalwart](../web-app-stalwart/), and both variants in [`meta/variants.yml`](./meta/variants.yml) deploy it. An inventory selects another provider only by overriding `applications.web-app-email.services.email.provider` and adding that role to its groups; the operator then owns the result.

## Adding a provider

A new mail server becomes selectable without touching any consumer:

1. Add the provider role and let its primary entity declare `covers: [email]`, which marks it as a mail provider.
2. Point `email.provider`, `email.run_after` and the provider service block of this role at it.

Every covering role that is not the selected provider counts as inactive: it publishes no onion ports and shares its host mail ports with the selected one.

[`test_mail_provider_reference.py`](../../tests/lint/ansible/services/test_mail_provider_reference.py) keeps every other role off the concrete provider ids and keeps the three keys of step 2 in agreement.
