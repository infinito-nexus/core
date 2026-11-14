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
7. **Rounding (operator pick 2026-11-14).** The core role pins the rounding every document of the site shares, and so extends the all-tenant structure of decision 2: `services.erpnext.rounding.method` (default `Banker's Rounding`) is the System Settings `rounding_method`, and `services.erpnext.rounding.row_wise_tax` (default `false`) is the Accounts Settings `round_row_wise_tax`. Both are inventory values that every deploy writes through an apply module beside the login methods, `files/python/apply/rounding.py`, and both are enforced fields of `meta/forms.yml`, so the desk locks them. The store's installer only asserts both values and never sets them.

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

### Rounding

- [x] `roles/web-app-erpnext/meta/services.yml` pins `services.erpnext.rounding.method` to `Banker's Rounding` and `services.erpnext.rounding.row_wise_tax` to `false`, and an inventory overrides either. `test_the_role_pins_bankers_rounding_and_rounds_tax_per_document`, `test_an_inventory_override_reaches_the_value_erpnext_stores` and `test_the_pinned_method_is_one_frappe_offers` in `tests/unit/python/roles/web-app-erpnext/test_forms_settings.py` prove it through `values` of `utils/roles/applications/converge.py`; they fail against the role before the change.
- [x] `roles/web-app-erpnext/meta/forms.yml` declares `rounding_method` as the enforced field of the form `system_rounding` on `/app/system-settings` `round_row_wise_tax` as the enforced field of `accounts_rounding` on `/app/accounts-settings`, and their sinks `ERPNEXT_SYSTEM_ROUNDING` and `ERPNEXT_ACCOUNTS_ROUNDING` (`vars/main.yml`) read only `lookup('form_values', ...)`. `test_the_renderer_locks_both_fields_with_their_inventory_path`, `test_the_sinks_read_only_their_forms` and `test_every_selector_names_its_doctype_and_field` in the same file prove the lock with its page and inventory path; the first two fail against the role before the change.
- [x] Every deploy writes both values through `roles/web-app-erpnext/files/python/apply/rounding.py`, beside the login methods: `tasks/01_manager_ops.yml` includes `tasks/06_rounding.yml` unconditionally, which reads both fields, reports the drift through `tasks/utils/forms/drift.yml` and then converges them through `tasks/utils/rounding.yml`. The module writes only the fields that differ, the System Settings as a saved document and the Accounts Settings field by `set_single_value`, commits only after a write and takes every value from its input. `tests/unit/python/roles/web-app-erpnext/files/apply/test_rounding.py` (11 tests) proves it on the fake site of `_fake_frappe.py`; mutants that write the System Settings by `set_single_value`, write unconditionally or hard-code the method each fail it. `test_every_deploy_pins_the_rounding`, `test_the_rounding_is_read_and_reported_before_the_write`, `test_both_rounding_modes_hand_the_sinks_to_the_script`, `test_only_a_converge_that_wrote_reports_a_change` and `test_the_rounding_report_reads_the_last_line_the_read_printed` in `test_forms_settings.py` prove the task wiring and fail against the role before the change.
- [x] The forms lint passes with both forms and fails on a negative control. `tests/lint/ansible/roles/meta/test_forms.py` passes over every role; against a copy of the role whose `rounding.py` hard-codes the method, `script_findings` reports `writes a literal to the field 'rounding_method'`, and against a copy whose `ERPNEXT_ACCOUNTS_ROUNDING` is a literal, `sink_findings` and `convergence_findings` report the sink and the unconverged form `accounts_rounding`.
- [ ] The store's installer asserts both values and sets neither.
- [ ] After a deploy the site holds `Banker's Rounding` and `0`, an admin change of either is reported and reverted by the next deploy, and the desk shows both fields locked with their inventory path.

### Coordination

- [ ] The PR of every ERPNext structure change on the store, security-check, store-i18n and IAM lines links the PRs of the other lines whose structure it relies on or changes; commits and PR descriptions name no requirement number.
- [ ] The store and the security check document in their own repositories which core prerequisites they rely on (server-script switch, API bot roles, company bootstrap) and point at this requirement.
