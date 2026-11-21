# 117 - Workspace Values of a Provision Run

## User Story

As the operator of a platform whose provision runs write DNS records into zones the platform chose, I want the workspace name, the deploy zone and the provider's zone id to reach every provision run from `workspace apply` alone, so that neither the store nor a workspace member can point a run at another workspace's name or at another zone.

## Background

The store's root modules (`interface.json`, `$defs.workspace`, in the store's core sidetree `feature/iam-reqs/062-tofu-root-modules`, commit `286b3689f1`) read a `workspace.json` beside the root with the workspace name and `dns.zone` and `dns.zone_id`. The store asked on 2026-11-13, as item (b) of its OpenTofu follow-ups, that the provision script write it; the operator took it the same day.

### Today

- A root takes exactly the six inputs of [104](104-runner-image-opentofu-and-root-modules.md) decision 4 from one `tfvars` file of the workspace checkout, and the provision script refuses any unknown key (104 decision 6). The zone and the workspace name are none of them.
- The deploy zone depends on the DNS flavor: the subzone under `knot` and `route53`, the zone `apply` placed the workspace in under `cloudflare` (104 decision 9). `apply` already writes it into the `deploy` template's environment as `WORKSPACE_DNS_ZONE` ([103](103-semaphore-pin-task-jwt-and-locked-templates.md) decision 7).
- The `route53` and `cloudflare` modules address a zone by the provider's zone id; `knot` updates by zone name only.

## Decisions

1. **`apply` writes the values.** `workspace apply` writes `WORKSPACE` (`ws-<id>`), `WORKSPACE_DNS_ZONE` and `WORKSPACE_DNS_ZONE_ID` into the environment of every `provision-<provider> ws-<id>` and `destroy-<provider> ws-<id>` ([133](133-provision-secrets-per-template.md)) and of `dns ws-<id>` ([115](115-dns-record-for-bring-your-own-servers.md)). `WORKSPACE_DNS_ZONE` is the value 103 decision 7 gives `deploy`. `WORKSPACE_DNS_ZONE_ID` is the id of the subzone's hosted zone under `route53`, the id of the placed zone under `cloudflare`, and empty under `knot`. None is a secret (103 decision 5), and the store, which holds `guest` there, cannot change a template's environment (104 decision 10).
2. **The script writes `workspace.json`.** Before `tofu init`, the provision script and the script of `dns ws-<id>` write `{"workspace": ..., "dns": {"zone": ..., "zone_id": ...}}` from these three values into the task directory beside the root, and validate it against `$defs.workspace` of `interface.json`. A missing or malformed value refuses the run and names the variable. Neither script takes these values from the survey or the checkout, and a root reads them only from this file, so the six inputs of 104 decision 4 stay as they are.

Rejected:

- The zone and the workspace name as `tfvars` keys: the workspace checkout would choose them.
- Survey variables: the store would choose them, while `apply` alone placed the workspace in its zone.

## Acceptance Criteria

- [x] After `workspace apply` under each DNS flavor, the environments of every `provision-<provider> ws-<id>` and `destroy-<provider> ws-<id>` and of `dns ws-<id>` hold `WORKSPACE`, `WORKSPACE_DNS_ZONE` and `WORKSPACE_DNS_ZONE_ID` with the values of decision 1, and `WORKSPACE_DNS_ZONE_ID` is empty under `knot` only (`test_apply_writes_the_workspace_values_per_flavor` in `tests/unit/python/roles/web-app-semaphore/test_dns_flavors.py`). (Against the fake Semaphore after a platform converge and a workspace apply; `test_the_operation_takes_the_values_from_the_flavor_fact_only` pins the `tasks/workspace.yml` source, and `test_negative_control_a_second_apply_under_another_zone_moves_every_template` moves all three templates; 25 tests green.)
- [x] The provision script writes a `workspace.json` that `$defs.workspace` accepts, and refuses, one case each, a missing `WORKSPACE`, a `WORKSPACE` outside `ws-<id>`, a malformed zone and a malformed zone id. A `zone` or `workspace` key in the `tfvars` file is refused as unknown and never reaches `workspace.json` (`test_provision_writes_workspace_json_from_the_environment` in `tests/unit/python/roles/web-app-semaphore/files/test_provision_sh.py`). (`workspace_document` in `roles/web-app-semaphore/files/python/provision/inputs.py` checks the document against `$defs.workspace`; the test reads the `workspace.json` the fake `tofu init` received and refuses each malformed value and each planted key; 35 tests green.)
- [ ] A provision of workspace A creates its record as `<label>.ws-<A>.<WORKSPACE_DNS_ZONE>` and returns that name as `fqdn` (`provision: the record lies in the workspace's zone` in `roles/web-app-semaphore/files/playwright/test-provision.js`).
- [x] The [README](../../roles/web-app-semaphore/README.md) documents the three environment values and `workspace.json`. (`WORKSPACE_VALUES` holds `workspace.json`, `WORKSPACE_DNS_ZONE` and `WORKSPACE_DNS_ZONE_ID`.)
