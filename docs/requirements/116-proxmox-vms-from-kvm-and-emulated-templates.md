# 116 - Proxmox VMs from KVM and Emulated Templates

## User Story

As the operator of a platform that provisions Proxmox VMs on targets with and without nested KVM, I want every workspace VM to be a clone of one of two core-built templates per node, one with KVM and one emulated, so that a target without KVM still runs VMs although the OpenTofu provider cannot switch KVM off, and a workspace token gains no more than the right to clone those two templates.

## Background

The store's Proxmox lane (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decision 18) found that the `proxmox` root module cannot set `kvm`, and asked on 2026-11-13 for the template route as item (a) of its OpenTofu follow-ups; the operator took it the same day.

### Today

- The `proxmox` root reads the node, the storage and `kvm` from the catalog region, so that a VM on a target without nested KVM starts emulated ([104](104-runner-image-opentofu-and-root-modules.md) decision 4). [110](110-proxmox-test-target-and-pool-token-per-workspace.md) decision 5 records per host whether nesting is on.
- A workspace token reaches only its own pool, storage and bridge (110 decision 1), and the root uses no snippet and no `source_file` (110 decision 2), so it cannot upload a disk image itself.
- `web-app-proxmox` creates no VM template.

### Upstream

| Fact | Source |
| --- | --- |
| The VM resource of `bpg/proxmox` `v0.119.0` has no `kvm` argument. Its client knows the API field `kvm`, but the resource never sets it; the only related argument is `kvm_arguments`, the raw `args` option. | `mkKVMArguments` in [vm.go:261](https://github.com/bpg/terraform-provider-proxmox/blob/v0.119.0/proxmoxtf/resource/vm/vm.go#L261) and [:501-505](https://github.com/bpg/terraform-provider-proxmox/blob/v0.119.0/proxmoxtf/resource/vm/vm.go#L501-L505), `KVMEnabled` in [vms_types.go:91-92](https://github.com/bpg/terraform-provider-proxmox/blob/v0.119.0/proxmox/nodes/vms/vms_types.go#L91-L92) |
| Proxmox VE lets only `root@pam` set `args`. | `check_vm_modify_config_perm` in [Qemu.pm:1067-1070](https://github.com/proxmox/qemu-server/blob/7f1c6d7e32b670f38a07f1cdf14a2c23903ade64/src/PVE/API2/Qemu.pm#L1067-L1070) |
| Cloning needs `VM.Clone` on the source VM and `VM.Allocate` on the new VM or its pool, plus `Datastore.AllocateSpace` on the storages and `SDN.Use` on the bridges it uses. | `clone_vm` in [Qemu.pm:4381-4401](https://github.com/proxmox/qemu-server/blob/7f1c6d7e32b670f38a07f1cdf14a2c23903ade64/src/PVE/API2/Qemu.pm#L4381-L4401) |
| The provider clones with `clone.vm_id` and `clone.full`; a clone on the template's own node reads nothing of the source VM first. | [vm.go:2337-2389](https://github.com/bpg/terraform-provider-proxmox/blob/v0.119.0/proxmoxtf/resource/vm/vm.go#L2337-L2389), the cross-node read at [:2392-2394](https://github.com/bpg/terraform-provider-proxmox/blob/v0.119.0/proxmoxtf/resource/vm/vm.go#L2392-L2394) |

## Decisions

1. **Two templates per node (operator pick, 2026-11-13).** The deploy of `web-app-proxmox` creates on each node of its Proxmox VE two VM templates from one pinned cloud image, `services.proxmox.workspaces.image` (URL and SHA-256): `kvm` with the VM option `kvm` 1, and `emulated` with `kvm` 0 and CPU type `qemu64`. Their ids are `services.proxmox.workspaces.templates.kvm` and `.emulated`, by default `9000` and `9001`. Each holds a cloud-init drive and no secret, and lives on the storage the catalog region names. The deploy keeps a template whose image digest is unchanged and replaces it otherwise, so a second deploy changes nothing. It runs these steps inside the guest as it runs `pveum` (110 decision 3).
2. **The root clones the region's template.** A catalog region of the `proxmox` root names its node, storage, bridge, `kvm` and `templates` (`kvm` and `emulated` ids). The root clones `templates.emulated` when the region's `kvm` is false, with CPU type `qemu64`, and `templates.kvm` otherwise, always as a full clone (`clone.full` true) on the template's node. So the `kvm` of 104 decision 4 takes effect through the template, and a template can be replaced without touching a VM cloned from it. The default proxmox catalog names the default ids; a deployment that changes one changes the other, which the README states.
3. **Clone only.** `workspace apply` adds, for the user `ws-<id>@pve` and its token, the role `InfinitoTemplateClone`, which holds `VM.Clone` and nothing else, on `/vms/<kvm id>` and `/vms/<emulated id>`. This is the only right outside the workspace's pool (110 decision 1). It copies a template that holds no secret, and neither changes, starts nor deletes it. `destroy` removes these ACLs with the token.

Rejected:

- `kvm_arguments` to switch KVM off: Proxmox lets only `root@pam` set `args` (Upstream), and the workspace token is not root.
- A second provider release or a fork that sets `kvm`: one more pin to track for one boolean.
- Templates inside each workspace pool: one image copy per workspace and per node, and the workspace token would hold `VM.Config.*` on them.
- Linked clones: a template could not be replaced while a VM uses its disk.

## Acceptance Criteria

### Templates

- [ ] The deploy creates both templates on each node: `kvm` with `kvm` 1 and `emulated` with `kvm` 0 and CPU `qemu64`, both from the pinned image. A second deploy changes neither (`proxmox templates: the deploy creates both templates once` in `roles/web-app-proxmox/files/playwright/test-workspace-pools.js`).
- [x] The rendered template steps set `kvm` 0 and `qemu64` for `emulated` and check the image's SHA-256 before the import; negative controls drop `kvm` 0 and the sum check, and each must fail (`test_the_templates_are_built_as_pinned` and its controls in `tests/unit/python/roles/web-app-proxmox/test_templates.py`). Met: the test runs `roles/web-app-proxmox/files/shell/templates.sh` against a faked `qm` and `curl`; `test_negative_control_a_dropped_kvm_0_fails`, `test_negative_control_a_dropped_sum_check_fails`, and `test_a_second_deploy_changes_neither_template` for the idempotence.

### Rights

- [x] The ACLs `apply` writes for a workspace hold, beside those of 110 decision 1, exactly `InfinitoTemplateClone` on the two template paths, and `InfinitoTemplateClone` holds exactly `VM.Clone`. A negative control adds `VM.Config.Disk` and must fail (`test_the_workspace_may_only_clone_the_templates` and its control in `tests/unit/python/roles/web-app-proxmox/test_workspace_role.py`). Met: the test and `test_negative_control_an_added_disk_right_on_the_templates_fails`; the ACLs come from `proxmox_workspace_acls` in `roles/web-app-proxmox/filter_plugins/proxmox_workspace.py`.
- [ ] With the token of workspace A, a full clone of each template into pool `ws-<A>` succeeds. Cloning any other VM outside pool `ws-<A>` and changing or deleting a template are refused (`proxmox workspaces: a token clones the templates and changes none` in `test-workspace-pools.js`).

### Root

- [x] The `proxmox` root clones `templates.emulated` with CPU `qemu64` for a region with `kvm` false and `templates.kvm` for one with `kvm` true, always with `clone.full` true. A negative control that swaps the templates must fail (`test_the_proxmox_root_takes_kvm_from_the_region`, the test 104 names, and this control in `tests/lint/repository/opentofu/test_root_modules.py`). (`kvm_findings` evaluates the root's `local.mode`, `local.cpu_type` and `clone` for both modes; `test_negative_control_swapped_templates_fail`, `test_negative_control_a_fixed_kvm_mode_fails` and `test_negative_control_a_linked_clone_fails` each fail it; 26 tests green.)
- [ ] On the CI target without nested KVM, a provisioned VM runs with `kvm` 0, boots and answers SSH (`provision: proxmox creates and destroys a server` in `roles/web-app-semaphore/files/playwright/test-provision.js`, from the row's deploy log).

### Documentation

- [x] The [README](../../roles/web-app-proxmox/README.md) documents both templates, the image pin, the template ids shared with the catalog, the full clones and the clone-only right (`test_the_readme_names_the_workspace_templates` in `tests/unit/python/roles/web-app-proxmox/test_readme.py`). Met: the test and its control that drops a template id.
