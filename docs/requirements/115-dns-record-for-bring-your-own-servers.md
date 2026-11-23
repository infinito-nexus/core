# 115 - DNS Record for Bring-Your-Own Servers

## User Story

As the operator of a platform that deploys onto servers its customers bring, I want one locked template per workspace that creates and removes the deploy record of such a line on its own, so that a BYO line gets the same `<dns_label>.ws-<id>.<zone>` name as a provisioned one, and its removal never touches a record it did not create.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decisions 12 and 17) sells BYO lines, which run on a customer's live server. The store asked for this template on 2026-11-13 as item 3 of its follow-up list, and the operator took it the same day.

### Today

- A provisioned line gets its record from the root module's `dns` module in the same OpenTofu state as its server, so `tofu destroy` removes both ([104](104-runner-image-opentofu-and-root-modules.md) decisions 3 and 5). A BYO line has no server state, so nothing creates or removes its record.
- The provision project holds `provision-<provider> ws-<id>` and `destroy-<provider> ws-<id>` per provider ([133](133-provision-secrets-per-template.md)) and `unlock ws-<id>`, which the store runs through `guest` and one grant per template (104 decisions 1 and 10). Only the provision runner holds the DNS credentials (104 decision 1).
- `workspace apply` writes `WORKSPACE_TARGETS`, the target pairs it pinned, into the `deploy` template's environment, and `deploy.sh` refuses a `HOST` outside them ([103](103-semaphore-pin-task-jwt-and-locked-templates.md) decision 7).

### Upstream

| Fact | Source |
| --- | --- |
| The `hashicorp/dns` provider `v3.6.2` creates an A record set by inserting its addresses into the name's RRset, and deletes it by removing the whole RRset of that name and type. So a record set created on a name that already holds addresses takes them into its state and deletes them on destroy. | `resourceDnsARecordSetCreate` and `resourceDnsARecordSetUpdate` in [resource_dns_a_record_set.go:63-165](https://github.com/hashicorp/terraform-provider-dns/blob/v3.6.2/internal/provider/resource_dns_a_record_set.go#L63-L165), `resourceDnsDelete` in [provider.go:692-711](https://github.com/hashicorp/terraform-provider-dns/blob/v3.6.2/internal/provider/provider.go#L692-L711) |
| Semaphore `v2.20.24` starts no task of a template while another task of it runs when the template does not allow parallel tasks. | [TaskPool.go:730-763](https://github.com/semaphoreui/semaphore/blob/v2.20.24/services/tasks/TaskPool.go#L730-L763) |

## Decisions

1. **One template per workspace.** `workspace apply` creates the locked template `dns ws-<id>` in the provision project beside the three templates of 104 decision 1, adds the grant of 104 decision 10 to it, and lists its id in the workspace's provision role of [105](105-openbao-task-jwt-auth-transit-tenant-kv-and-store-approle.md) decision 2, so its task reads the workspace's DNS credential and state key. `destroy` removes it with the others. It runs on the provision runner.
2. **Inputs.** Its survey holds exactly `DNS_ACTION` (`create`, `remove` or `unlock`), `SALES_ORDER`, `LINE`, `HOST` and `DNS_LABEL`, each with target `env` (103 decision 4). `SALES_ORDER`, `LINE` and `DNS_LABEL` carry the patterns of 104 decisions 4 and 6. `HOST` is one IPv4 or IPv6 address, or a fully qualified host name matching `$defs.host_name` of `interface.json`, the pattern `workspace.py` checks `WORKSPACE_TARGETS` with (decision 7). Either MUST be the host of a pair of `WORKSPACE_TARGETS`, which `apply` writes into this template's environment as it does for `deploy`. `create` needs all four values; `remove` and `unlock` need `SALES_ORDER` and `LINE` only. The script reads nothing from the workspace checkout: every value comes from the survey and the template environment.
3. **The record lives in a state of its own.** `roles/web-app-semaphore/files/opentofu/records/` is a root module that only calls `modules/dns` (104 decision 3) with the name `<DNS_LABEL>.ws-<id>` and either `HOST` as its one address (`host`) or `HOST` as the target of a CNAME (`cname`), and returns `fqdn`. Its state key is `<SALES_ORDER>/<LINE>.dns.tfstate` in the workspace's state bucket, with the backend, lock and encryption of 104 decision 7. A server state and a record state therefore never share a key, so a `provision` of the same line cannot plan to destroy this record, nor this root a server.
4. **Idempotent create, exact remove.** `create` runs `tofu apply`: a repeated `create` with the same values changes nothing, and one with a new `HOST` changes the address. `remove` runs `tofu destroy`, which deletes only what this state holds, and succeeds with nothing to do when the state is empty or missing: it then deletes the empty state and its lock without a `tofu destroy` and ends, like every remove, with `{"destroyed": [], "state": "deleted"}` (104 decision 12).
5. **One name, one line.** Before the first `apply` of an empty state, the script asks the zone's authoritative servers for A, AAAA and CNAME records of the name and refuses when any exists, because a CNAME cannot share its name with another record. Under the `knot` flavor a record set would otherwise take the other line's address into its state and remove it on `remove` (Upstream). The provision script of 104 runs the same check before the first `apply` of a server state, so a provisioned line and a BYO line never share a name either.
6. **Stale locks.** `dns ws-<id>` does not allow parallel tasks (103 decision 3), so while an `unlock` task runs no other task of it runs (Upstream). `unlock` therefore force-unlocks the record state of `SALES_ORDER` and `LINE` with the lock id read from its `.tflock` object, with no further check.
7. **A host name writes a CNAME (Store ask 33, robot pick, 2026-11-14).** A BYO host may be a name, and `WORKSPACE_TARGETS` keeps names. When `HOST` is a name, `create` writes the CNAME `<DNS_LABEL>.ws-<id>.<zone>` to it under every flavor; an address keeps writing A or AAAA. Core never resolves the name, so there is no stale snapshot and no spoofable answer, and the record follows the customer's own DNS. The `knot` ACL and the `route53` policy of 104 decision 9 therefore admit CNAME beside A, AAAA and TXT.

Rejected:

- A script per DNS flavor (`nsupdate`, the AWS CLI, the Cloudflare API): three more implementations of what `modules/dns` does, without a state that says which record a line created.
- The server state key `<SALES_ORDER>/<LINE>.tfstate` for the record: an `apply` of the other root on the same key would destroy what the first created.
- A record written by `sys-dns-cloudflare-records`: store decision 18 rejected it, because removal on destroy needs its own path.
- The record on a workspace runner: it holds no DNS credential (104, isolation criterion).

## Acceptance Criteria

### Template

- [ ] `workspace apply` creates exactly one locked `dns ws-<id>` in the provision project with the store's grant, and `destroy` removes it with its grant (`provision rights: apply creates the dns template with its grant` in `roles/web-app-semaphore/files/playwright/test-provision.js`).
- [x] The survey of `dns ws-<id>` holds exactly `DNS_ACTION`, `SALES_ORDER`, `LINE`, `HOST` and `DNS_LABEL`, each with target `env`, and its environment holds `WORKSPACE_TARGETS` and no secret (`test_the_dns_survey_is_fixed` in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`, 68 tests green; the planted survey variable, the survey variable without target `env` and the environment with a secret and no `WORKSPACE_TARGETS` fail it).
- [x] The script refuses, one case each and naming the variable, an unknown `DNS_ACTION`, a malformed `SALES_ORDER`, `LINE` or `DNS_LABEL`, a `HOST` that is neither an address nor a host name of `$defs.host_name`, even when `WORKSPACE_TARGETS` lists it, and a `HOST` outside `WORKSPACE_TARGETS`, and reads no file of the checkout (`test_dns_sh_refuses_each_malformed_input` and `test_dns_sh_reads_no_file_of_the_checkout` in `tests/unit/python/roles/web-app-semaphore/files/test_dns_sh.py`, 14 tests green at the lane tip; the planted regressions that accept a host outside the targets, loosen the host name pattern or read the checkout fail them).
- [x] `create` with a host name of `WORKSPACE_TARGETS` hands the record root `cname` set to that name and `host` empty, and asks DNS only about its own name `<DNS_LABEL>.ws-<id>.<zone>`, never about the target; a host name outside `WORKSPACE_TARGETS` is refused before any query or OpenTofu call (decision 7) (`test_a_host_name_of_the_targets_writes_a_cname_and_is_never_resolved` and `test_negative_control_a_host_name_outside_the_targets_is_refused` in `test_dns_sh.py`, `TestRecordTarget` in `tests/unit/python/roles/web-app-semaphore/files/provision/test_inputs.py`, green at the lane tip; the planted regressions that admit a name outside the targets and that write the name as an address fail them).
- [x] Every flavor module writes exactly one CNAME, only while `cname` is set and to that name, no address record reads `cname`, the record root passes its `cname` and every server root passes an empty one (`test_every_dns_flavor_writes_a_cname_only_for_a_name`, its controls for a missing and an unconditional CNAME, and `test_only_the_record_root_passes_a_cname` in `tests/lint/repository/opentofu/test_root_modules.py`, green at the lane tip).

### Record

- [ ] Under each DNS flavor that has credentials, `create` makes `<label>.ws-<A>.<zone>` resolve to `HOST`, a second `create` changes nothing, `remove` deletes it, and a second `remove` succeeds (`dns: a BYO record is created once and removed` in `test-provision.js`).
- [x] A `remove` of a missing or empty record state deletes the state and its lock without a `tofu destroy` and ends with `{"destroyed": [], "state": "deleted"}`, so the store reads a finished remove from the same line as every other one (`test_remove_without_a_state_succeeds_with_nothing_to_do` and `test_remove_of_an_empty_state_deletes_it_and_its_lock` in `tests/unit/python/roles/web-app-semaphore/files/test_dns_sh.py`; the former prose line `<key> holds no record` fails both).
- [ ] `remove` of one line leaves the record of another line of the same workspace in place (`dns: remove deletes only its own record` in `test-provision.js`).
- [x] `create` of a CNAME refuses a name that already holds an A, AAAA or CNAME record its own state does not hold, before any write (`test_a_cname_refuses_a_name_that_holds_any_record` in `test_dns_sh.py` and `test_a_cname_alone_takes_a_name` with its in-file control that an A and AAAA guard alone misses the CNAME in `files/provision/test_remote.py`, green at the lane tip; the planted guard that asks A and AAAA only fails both).
- [ ] `create` of a name that already holds an A, AAAA or CNAME record is refused before any write, and so is a `provision` whose `dns_label` names such a record; a negative control without the check must lose the other line's record under `knot` (`dns: a taken name is refused` in `test-provision.js`; the control `dns: without the taken-name check a create loses the other line's record` there writes a second line's A record on the taken name and removes its record set with the workspace's TSIG key, as the `hashicorp/dns` provider does (Upstream), with no check of `dns.sh` in between, and the owner's record must be gone; production code holds no switch that skips the check).
- [ ] The backend configuration of the record root names the key `<SALES_ORDER>/<LINE>.dns.tfstate` in the workspace bucket with `use_lockfile = true`, and the state object is OpenTofu's encrypted envelope (`test_the_record_state_has_its_own_key` in `tests/unit/python/roles/web-app-semaphore/files/test_dns_sh.py`; `dns: the record state is encrypted` in `test-provision.js`).
- [ ] `unlock` removes a lock left on a record state (`dns: unlock clears a stale record lock` in `test-provision.js`).

### OpenBao

- [ ] Under the knot and route53 flavors, a task of `dns ws-<A>` logs in only to the role `ws-<A>-provision`, whose one role policy (beside OpenBao's built-in `default`) reads `tenant/data/ws-<A>-provision/dns` and holds no path that covers `tenant/data/ws-<B>-provision/dns`, so OpenBao denies that read (under cloudflare the dns credential is the zone token `platform/data/provision/cloudflare/<zone>`, read by every workspace placed in that zone, which this box does not isolate) (`TestTheDnsTokenReachesNoProvisionPathOfAnotherWorkspace` in `tests/unit/python/roles/web-app-openbao/test_dns_template_isolation.py`; the planted provision role without its template binding and the planted grants `tenant/data/+/dns` and `tenant/data/ws-*` fail it; live, `provision login: the dns template reads only its own workspace` in `roles/web-app-semaphore/files/playwright/test-workspace-logins.js` runs `dns ws-<B>` and shows that a provision-project template the role does not bind is refused).

### Documentation

- [x] The [README](../../roles/web-app-semaphore/README.md) documents `dns ws-<id>`, its actions and inputs, its state key, the taken-name check and that a removal deletes only its own record (`roles/web-app-semaphore/README.md`).
