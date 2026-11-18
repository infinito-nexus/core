# 124 - Cloudflare Zone Lifecycle per Line

## User Story

As the operator of a platform whose store sells a customer domain as an order line, I want one locked template per workspace that creates, shows and deletes that domain's Cloudflare zone with core's own token, so that the store holds no Cloudflare credential and every zone change stands in a task log with its own state.

## Background

The store asked on 2026-11-13 (Store ask 34) for a core-owned zone lifecycle, and the operator filed this requirement on 2026-11-14 to be built after the IAM store round. Until it exists the store keeps its mock and sets no Cloudflare token of its own.

### Today

- `services.semaphore.workspaces.dns.flavor` picks `knot`, `route53` or `cloudflare` for the deploy records of a workspace ([104](104-runner-image-opentofu-and-root-modules.md) decision 9). Under `cloudflare` the deploy writes one token per zone of a fixed pool to `platform/data/provision/cloudflare/<zone>`, and `workspace apply` places a workspace in one of those zones. No template creates or deletes a zone.
- `dns ws-<id>` writes the record of a bring-your-own line in a state of its own, `<SALES_ORDER>/<LINE>.dns.tfstate`, in the workspace's state bucket ([115](115-dns-record-for-bring-your-own-servers.md) decision 3).
- The provision project runs on the provision runner, the only runner that holds provider and DNS credentials, and the store starts its workspace templates through `guest` and one grant per template (104 decisions 1 and 10).

## Decisions

1. **One template per workspace.** `workspace apply` creates the locked template `zone ws-<id>` in the provision project beside `provision`, `destroy`, `unlock` and `dns`, adds the grant of 104 decision 10 to it, and binds its id to a task token role of its own, `ws-<id>-zone`, and `workspace destroy` removes all three. It runs on the provision runner.
2. **Inputs.** Its survey holds exactly `ZONE_ACTION` (`create`, `show`, `delete` or `unlock`), `SALES_ORDER`, `LINE` and `DOMAIN`, each with target `env`. `SALES_ORDER` and `LINE` carry the patterns of the order line, `DOMAIN` the zone pattern `ZONE_PATTERN` of `lib.sh`. `create` and `show` need all four; `delete` and `unlock` need `SALES_ORDER` and `LINE` only. The script refuses any argument, a variable its action does not take and a malformed value, naming the variable, and reads no file of the workspace checkout.
3. **Core's token, never the store's.** The zone token is a role secret of `web-app-semaphore` with the right to create and delete zones in one Cloudflare account and nothing else, which the deploy writes to `platform/data/provision/cloudflare-zones` from stdin. Only the zone role `ws-<id>-zone` reads it: its policy `ws-<id>-zone` grants that token, the workspace's state bucket keys, its transit key and its snapshot record and nothing else, and the shared provision policy denies the token, so a `provision`, `destroy`, `unlock` or `dns` run of any workspace never reaches it and a zone run reaches no other provider secret. No task output carries it.
4. **The zone lives in a state of its own.** A root module under `roles/web-app-semaphore/files/opentofu/` holds only the zone, with the state key `<SALES_ORDER>/<LINE>.zone.tfstate` in the workspace's state bucket and the backend, lock and encryption of the server state. So a `provision`, `destroy` or `dns` of the same line never plans a change of the zone.
5. **Idempotent create, exact delete.** `create` runs `tofu apply`, so a repeated `create` changes nothing, and refuses a `DOMAIN` that the account already holds outside this state. `delete` runs `tofu destroy` and succeeds with nothing to do when the state is empty or missing. `unlock` force-unlocks the zone state with the lock id of its `.tflock` object. A state that holds resources without the zone outputs, as an interrupted apply leaves it, makes `create` and `show` fail without a change, while `delete` reads the domain from the zone resource in the state and destroys it, failing without a change only when the state names no zone; `unlock` does not read the state.
6. **Output.** The last output line of `create` and `show` is one JSON object with exactly `zone`, `zone_id`, `status` (the provider's zone status) and `name_servers`, the assigned name servers the customer sets at the registrar. `show` reads the state and the provider and writes nothing. `delete` prints `{"deleted": true, "zone": "<domain>"}`, and `{"deleted": true, "zone": null}` when the state of the line is empty or missing and so names no domain.
7. **Destroy order.** `workspace destroy` refuses while the bucket still holds a `.zone.tfstate`, as it does for a server state, so no zone outlives its workspace.

## Acceptance Criteria

### Template

- [ ] `workspace apply` creates exactly one locked `zone ws-<id>` in the provision project with the store's grant, and `destroy` removes it with its grant (`provision rights: apply creates the zone template with its grant` in `roles/web-app-semaphore/files/playwright/test-provision.js`).
- [ ] The survey of `zone ws-<id>` holds exactly `ZONE_ACTION`, `SALES_ORDER`, `LINE` and `DOMAIN`, each with target `env`, and its environment holds no secret; a planted survey variable fails the check (`test_the_zone_survey_is_fixed` in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`).
- [ ] The script refuses, one case each and naming the variable, any argument, an unknown `ZONE_ACTION`, a malformed `SALES_ORDER`, `LINE` or `DOMAIN` and a variable its action does not take, before any OpenTofu call, and reads no file of the checkout (`test_zone_sh_refuses_each_malformed_input` in `tests/unit/python/roles/web-app-semaphore/files/test_zone_sh.py`).

### Credential

- [ ] Only the zone role of a workspace reads `platform/data/provision/cloudflare-zones`; the provision, store, workspace and export task tokens each get 403 on it, and the zone policy reaches nothing of another workspace or provider (`test_only_the_zone_role_reads_the_zone_token`, `test_the_zone_policy_reaches_its_own_workspace_and_the_zone_token_only` and `test_the_zone_policy_reads_no_other_workspace_or_provider` in `tests/unit/python/roles/web-app-openbao/test_policies.py`; `test_no_other_role_binds_the_zone_template` with its planted control in `tests/unit/python/roles/web-app-openbao/test_workspace_roles.py`; `test_the_zone_run_logs_in_with_the_zone_role_only` in `test_zone_sh.py`; live, `store approle: reads no zone token` in `roles/web-app-openbao/files/playwright/test-task-login.js` proves it for the store token and `provision isolation: a workspace task reads no provision secret` in `roles/web-app-semaphore/files/playwright/test-provision.js` for a workspace task token, whose own tenant path answers 404).
- [ ] No task output, argument or environment value of `zone ws-<id>` carries the token (`test_the_zone_token_reaches_no_output` in `test_zone_sh.py`, with a planted echo of the token as its negative control).

### Lifecycle

- [ ] Under credentials, `create` makes the zone exist with the status the provider reports, a second `create` changes nothing, `show` prints the same `zone_id`, `delete` removes the zone and a second `delete` succeeds (`zone: a zone is created once, shown and deleted` in `test-provision.js`).
- [ ] The backend configuration names the key `<SALES_ORDER>/<LINE>.zone.tfstate` with `use_lockfile = true`, and the state object is OpenTofu's encrypted envelope (`test_the_zone_state_has_its_own_key` in `test_zone_sh.py`).
- [ ] `create` of a `DOMAIN` the account already holds outside this state is refused before any write (`zone: a foreign zone is refused` in `test-provision.js`).
- [ ] A state that holds the zone without its outputs makes `create` and `show` fail without a change, `delete` destroys it with the domain of its zone resource and the zone token, a state that names no zone stays, a stale `.tflock` makes `delete` fail until `unlock` removes it, and a state without resources is forgotten (`test_delete_destroys_a_state_an_interrupted_create_left`, `test_negative_control_create_and_show_refuse_that_state`, `test_delete_keeps_a_state_it_cannot_read_the_zone_from`, `test_a_stale_lock_blocks_delete_until_unlock` and `test_negative_control_a_state_without_resources_is_forgotten` in `test_zone_sh.py`).
- [ ] `workspace destroy` refuses while a `.zone.tfstate` remains (`test_destroy_refuses_a_remaining_zone_state` in `tests/unit/python/roles/web-svc-seaweedfs/`).

### Documentation

- [ ] The [README](../../roles/web-app-semaphore/README.md) documents `zone ws-<id>`, its actions, inputs, output line, state key and the token's reach (`roles/web-app-semaphore/README.md`).
