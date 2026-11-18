# 126 - SCS Customer Application Credential

## User Story

As a customer who orders servers on my own Sovereign Cloud Stack project, I want the provision templates to accept my OpenStack application credential the way they accept my Hetzner or IONOS token, so that my servers run and bill in my own project while core never trusts an endpoint or a credential scope it did not check.

## Background

The operator filed this follow-up on 2026-11-14, to be built after the IAM store round.

### Today

- `provision ws-<id>` and `destroy ws-<id>` take `PROVIDER_TOKEN`, `platform` or `workspace` (Store ask 28). Under `workspace`, `hetzner` and `ionos` read the customer's token at `tenant/data/ws-<id>-provision/providers/<provider>`, field `token`, and neither source falls back to the other (`provider_secrets` in `roles/web-app-semaphore/files/python/provision/provider_env.py`, `workspace_secrets` in `roles/web-app-semaphore/files/opentofu/credentials.json`).
- `scs` has no `workspace_secrets`, so `PROVIDER_TOKEN=workspace` on `scs` refuses before OpenTofu starts. Its `platform` source reads `auth_url`, `region_name`, `application_credential_id` and `application_credential_secret` from `tenant/data/ws-<id>-provision/scs`.
- A region of the catalog names its provider and its sizes ([118](118-provision-catalog-per-deployment.md)); the root modules are listed in [104](104-runner-image-opentofu-and-root-modules.md).

## Decisions

1. **The same path as the other providers.** The customer's credential lives at `tenant/data/ws-<id>-provision/providers/scs` with exactly the fields `application_credential_id` and `application_credential_secret`, written by the store like the Hetzner and IONOS tokens, and `credentials.json` gives `scs` a `workspace_secrets` entry for it.
2. **Core picks the endpoint.** The Keystone `auth_url` and the region come from the catalog region of the order, never from the customer's record, so a customer cannot point the provision runner at a host of its choice. A record that carries `auth_url` or `region_name` is refused.
3. **The contract of the credential.** Before OpenTofu starts, the provision checks the credential against Keystone: it MUST authenticate, MUST be scoped to exactly one project, MUST NOT be `unrestricted`, so it cannot mint further credentials, and MUST NOT expire before the run ends. A credential that fails any of these refuses the run, naming the rule, and the check prints no part of the secret.
4. **No fallback.** `PROVIDER_TOKEN=workspace` on `scs` uses only the customer's credential and `platform` only the platform's, as for the other providers.

## Acceptance Criteria

### Inputs

- [ ] `PROVIDER_TOKEN=workspace` on an `scs` region reads `tenant/data/ws-<id>-provision/providers/scs` and hands OpenTofu its two fields with the `auth_url` and region of the catalog region (`test_scs_workspace_credential_uses_the_catalog_endpoint` in `tests/unit/python/roles/web-app-semaphore/files/test_provision.py`).
- [ ] A missing or empty field, and a record that carries `auth_url` or `region_name`, refuse the run before OpenTofu starts, naming the field (`test_scs_workspace_credential_refuses_a_foreign_endpoint` in `test_provision.py`, with a planted record whose `auth_url` would be used as its negative control).
- [ ] `PROVIDER_TOKEN=workspace` never falls back to the platform credential of `scs`, and `platform` never reads the customer's record (`test_scs_sources_never_fall_back` in `test_provision.py`).

### Contract

- [ ] An unrestricted credential, one scoped to no project or to more than one, and one that expires within the run's time budget each refuse the run before any write, naming the rule, and the output carries no part of the secret (`test_scs_credential_contract` in `tests/unit/python/roles/web-app-semaphore/files/provision/test_keystone.py`).
- [ ] Under credentials of a test project, a `provision` with a valid customer credential creates the server in that project and `destroy` removes it (`provision: scs runs in the customer's own project` in `roles/web-app-semaphore/files/playwright/test-provision.js`).

### Documentation

- [ ] The [README](../../roles/web-app-semaphore/README.md) documents the `scs` customer credential, its path, its two fields, the endpoint rule and the contract (`roles/web-app-semaphore/README.md`).
