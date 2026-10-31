# 067 - ERPNext Structure Coordination

## User Story

As a platform operator, I want the ERPNext structure that the core role, the Infinito.Nexus store (GUI) and the security check (Security) build on one ERPNext site to stay compatible, so that no line strips, disables or overwrites what another line created, and every tenant gets only the structure that holds for every tenant.

## Decisions (operator-confirmed 2026-10-31; do not re-litigate)

1. **Chair.** The IAM line (`feature/iam-profile-rbac`) chairs the ERPNext structure. GUI, Security and store-i18n announce every change to the ERPNext structure to the chair before it lands, and a conflict in `roles/web-app-erpnext` resolves by this document.
2. **Split.** `roles/web-app-erpnext` carries only what holds for every tenant: SSO and LDAP sign-in, the RBAC role mapping, the login methods of 064, the API bot, the server-script switch and the company bootstrap. The store commerce structure (GUI, `web-app-cst-store`) and the security-check structure (Security, `web-app-cst-security-check`) are Infinito.Nexus-internal; they live in their own repositories and roles and are created at runtime against the core site.
3. **One writer for the API bot.** The core role is the only writer of the roles and the API key and secret of `erpnext-api-bot`. A consumer declares the extra ERPNext roles it needs in the inventory, and the core role grants them; a declared role the site lacks is created as an empty Role first, so the grant never waits for the consumer's deploy.
4. **Directory-owned accounts only.** The RBAC sync and the sign-in mapping demote or disable only accounts the directory owns: members of a role group and accounts linked to the Keycloak social login or the LDAP source. Service, API, website and customer accounts that a consumer created keep their roles and stay enabled. On a directory-owned account the sync revokes only the roles the mapping manages and never disables an account that still holds a role granted outside the mapping (such as `Security Check Approver` or `Security Check Editor`).
5. **Namespaces.** Each consumer creates its custom fields, roles, DocTypes, server scripts and webhooks under its own reserved names, and the core role creates nothing under them beyond the empty Role of a name the consumer declared in `api_bot.extra_roles` (decision 3):
   - security check: custom fields `custom_secchk_*`, roles and DocTypes `Security Check *`, webhooks `security-check-*`;
   - store: item codes `INF::*`, pricing rules `INF-PR-*`, the webhooks `infinito-invoice-submitted`, `infinito-payment-entry-submitted`, `infinito-sales-order-active`, `infinito-sales-order-provisioning` and `infinito-sales-order-state-change` (reserved by name, since the core role uses `infinito-` itself), notifications and server scripts `Platform-*`, the workflow `Sales Order Lifecycle`, the print format `Infinito Sales Invoice`, the role `Provisioning Bot`, and exactly these custom fields (no store prefix, reserved by name): `custom_auto_topup_amount`, `custom_auto_topup_enabled`, `custom_auto_topup_threshold`, `custom_availability`, `custom_capacity_gb`, `custom_cpu_vcores`, `custom_device_subtype`, `custom_dns_provider_id`, `custom_keycloak_sub`, `custom_kind`, `custom_linux_compatible`, `custom_max_negative_balance`, `custom_memory_gb`, `custom_platform_bundle_id`, `custom_platform_label`, `custom_platform_profile`, `custom_registrar_provider_id`, `custom_sales_partner`, `custom_sepa_mandate_id`, `custom_storage_gb`, `custom_tld`, `custom_workflow_version`. A new store field is added to this list.
6. **API bot roles of the Infinito.Nexus inventory.** `services.erpnext.api_bot.extra_roles` there holds the union of the consumers' needs: store `System Manager`, `Provisioning Bot`, `Sales Master Manager`, `Sales Manager`, `Sales User`, `Item Manager`, `Stock Manager`, `Accounts User`; security check the roles its provisioning needs on the bot. Other tenants keep the empty default.

## Acceptance Criteria

### Ownership

- [x] The README of `roles/web-app-erpnext` lists the all-tenant structure it owns, the consumers that build on it (store, security check) and what each consumer may create on the site.
- [x] No file under `roles/web-app-erpnext` creates store or security-check structure; a lint fails when a reserved prefix or reserved name of decision 5 appears in the role, and it fails on a negative control.

### API bot

- [x] `applications.web-app-erpnext.services.erpnext.api_bot.extra_roles` is an inventory list of ERPNext roles the core role grants to `erpnext-api-bot` beside its own; it defaults to an empty list and the store and the security check declare their needs there.
- [x] A declared role the site lacks is created as an empty Role and granted in the same run, and a unit test proves it with `Provisioning Bot` on a fresh site.
- [ ] The core role is the only place that sets the roles, the API key and the API secret of `erpnext-api-bot`, and the store's `ensure_api_roles` no longer sets either.
- [ ] With `server_scripts` on, `erpnext-api-bot` can create Roles, DocTypes, Custom Fields, Server Scripts, Webhooks and Users, proven by a check against a deployed site.

### RBAC scope

- [x] The RBAC sync (`files/python/apply/rbac_roles.py`) neither revokes roles from nor disables an account that is not directory-owned, and a unit test proves it with a consumer API user and a website customer.
- [x] On a directory-owned account outside every role group the sync revokes only managed roles and keeps the account enabled while it holds an unmanaged role, and a unit test proves it with a staff account holding `Security Check Approver`.
- [x] The sign-in mapping of `infinito_rbac` changes only the account that signs in through Keycloak or LDAP.
- [ ] After two RBAC sync runs on a site with the security check and the store provisioned, the security check's API user keeps its seven roles and stays enabled, and the store's accounts keep theirs.

### Coordination

- [ ] Every ERPNext structure change on the store, security-check, store-i18n and IAM lines from now on names this requirement in its commit or PR description.
- [ ] The store and the security check document in their own repositories which core prerequisites they rely on (server-script switch, API bot roles, company bootstrap) and point at this requirement.
