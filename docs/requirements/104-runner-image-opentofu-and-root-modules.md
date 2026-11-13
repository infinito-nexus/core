# 104 - Runner Image: OpenTofu and Root Modules

## User Story

As the operator of a platform that provisions customer servers at Hetzner, IONOS, SCS, Proxmox and Incus, I want one pinned OpenTofu with an offline provider mirror and one core root module per provider in the provision runner, fed only with schema-checked values, with its state locked and encrypted per workspace, so that every server is created and destroyed by reviewed platform code and no customer file or value runs as infrastructure code.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decisions 8, 11 and 18, criteria 062:80, 062:105, 062:132-136) needs this core side. Decision 18 places the root modules in core, baked into the runner image and versioned with the core tag. The store line writes the modules in a core sidetree, with the IAM line's consent per bundle; this requirement is their contract.

### Today

- No core file installs or runs OpenTofu or Terraform: the root `Dockerfile`, `cli/`, `plugins/`, `utils/` and every role's tasks hold neither; the two hits under `roles/web-app-semaphore` are descriptions (`meta/main.yml:4`, `README.md:5`).
- The runner builds on the Infinito.Nexus image of the deploy (`roles/web-app-semaphore/files/runner/Dockerfile:5`) and links its scripts from that image's core tree (`Dockerfile:21`). A file under `roles/web-app-semaphore/files/` is therefore in the runner image of the same core tag.
- The only cloud API core drives is reverse DNS at Hetzner (`hetzner.hcloud` in `requirements/requirements.galaxy.yml`, used by `roles/sys-dns-hetzner-rdns/tasks/flavors/cloud.yml`).

### Upstream

| Fact | Source |
| --- | --- |
| The S3 backend locks with a `.tflock` object written by a conditional `PutObject` when `use_lockfile = true` (OpenTofu 1.10 and later), with no DynamoDB table. | [OpenTofu S3 backend](https://opentofu.org/docs/language/settings/backends/s3/) |
| An S3-compatible endpoint needs `endpoints.s3`, `use_path_style`, `skip_credentials_validation`, `skip_region_validation`, `skip_requesting_account_id`, `skip_metadata_api_check` and, for some servers, `skip_s3_checksum`. | [OpenTofu S3 backend](https://opentofu.org/docs/language/settings/backends/s3/) |
| State encryption (OpenTofu 1.7 and later) has the key provider `openbao` with `key_name`, `token` (or `BAO_TOKEN`), `address` (or `BAO_ADDR`), `transit_engine_path` (default `/transit`) and `key_length` (16, 32 or 64). `enforced = true` in `state` and `plan` refuses to write unencrypted data. The whole configuration can come from `TF_ENCRYPTION`. | [OpenTofu state encryption](https://opentofu.org/docs/language/state/encryption/) |
| A CLI configuration whose `provider_installation` lists only a `filesystem_mirror` installs providers from that directory and never from the network. | [OpenTofu CLI configuration](https://opentofu.org/docs/cli/config/config-file/) |
| The providers: `hetznercloud/hcloud`, `ionos-cloud/ionoscloud`, `terraform-provider-openstack/openstack`, `bpg/proxmox`, `lxc/incus`, `cloudflare/cloudflare`. | [OpenTofu registry](https://search.opentofu.org/) |
| A Cloudflare API token is scoped to zones and permissions, not to record names. A subdomain as a zone of its own is available on the Enterprise plan only. | [Cloudflare API token permissions](https://developers.cloudflare.com/fundamentals/api/reference/permissions/), [subdomain setup](https://developers.cloudflare.com/dns/zone-setups/subdomain-setup/) |
| SeaweedFS 4.53 carries the fix for a conditional `PutObject` on a versioned bucket that was accepted but unreadable after a racing `DELETE`, reported on 4.52 by an OpenTofu `use_lockfile` user. | [seaweedfs#12453](https://github.com/seaweedfs/seaweedfs/issues/12453), [seaweedfs#12454](https://github.com/seaweedfs/seaweedfs/pull/12454) |

## Decisions

1. **Provisioning runs on the platform's provision runner.** The platform project `<SOFTWARE_NAME> Provision` (102 decision 2) holds, per workspace, the locked templates `provision ws-<id>`, `destroy ws-<id>` and `unlock ws-<id>`. `workspace apply` creates them. They run on the provision runner, never on a workspace runner. That runner holds tokens that cannot be scoped per workspace (Hetzner Cloud, IONOS) and the DNS token. A workspace runner runs code a workspace member can change, so it never holds them (store criterion 062:136). The per-workspace templates give each workspace its own `template_id`, which its OpenBao role binds (105). The provision runner gets the egress proxy of 102 decision 6, with the provider API hosts, Cloudflare, OpenBao, the S3 endpoint, Gitea and the Semaphore server on its list.
2. **Pinned OpenTofu with an offline mirror.** The runner build installs one pinned OpenTofu release of at least 1.10.0 from its release archive and checks its SHA-256 sum, which core pins. For every root module the build mirrors the providers its `.terraform.lock.hcl` pins (`tofu providers mirror`). The image's CLI configuration names only that `filesystem_mirror`. A provider that is missing fails the build, never a task.
3. **Root modules in core.** `roles/web-app-semaphore/files/opentofu/roots/<provider>/` holds one root module each for `hetzner`, `ionos`, `scs`, `proxmox` and `incus`. Each pins its providers to exact versions and carries its lock file. `roles/web-app-semaphore/files/opentofu/modules/dns-cloudflare/` holds the shared DNS child module. The modules sit in the core tree of the image, so they follow the core tag.
4. **One interface.** `roles/web-app-semaphore/files/opentofu/interface.json` is a JSON Schema of the inputs plus the list of outputs. Every root takes exactly these inputs:
   - `name`: the state key's name;
   - `flavor`: `demo` or `cloud`;
   - `size`: a catalog size the module maps to a server type;
   - `region`;
   - `ssh_public_key`;
   - `dns_label`.

   Every root returns exactly these outputs:
   - `host`: its public addresses;
   - `host_key`: the SSH host public key;
   - `server_id`;
   - `fqdn`.

   `host_key` comes from a key the module generates and installs through the provider's cloud-init user data. A provider that cannot take user data over its API leaves it empty, and the first contact pins the key (110 for Proxmox).
5. **DNS in the same state.** Each root creates the per-deploy record `<dns_label>.<deploy zone>` with the `dns-cloudflare` module, so `tofu destroy` removes it with the server (store decision 18). Which zone that is, is the open decision below.
6. **Values only, from JSON.** The provision script reads one `provision/<sales order>-<line>.tfvars.json` from the workspace checkout and validates it against `interface.json`: no unknown key, typed values, a size and region from the catalog. It refuses the run when the checkout holds any `*.tf`, `*.tf.json`, `*.tofu`, `*.tofu.json`, `.terraformrc` or `.tofurc`. It copies the root module from the image into the task directory and runs OpenTofu there, never in the checkout. It clears every `TF_*` variable it did not set itself, so a template environment cannot pass `TF_CLI_ARGS`.
7. **State per Sales Order and line.** The S3 backend uses:
   - the workspace's bucket `ws-<id>-state` (108);
   - the key `<sales order>/<line>.tfstate`, never the run, so a retry applies to the same server (store criterion 062:133);
   - `use_lockfile = true`;
   - the SeaweedFS endpoint with the S3-compatible settings above.

   The state is encrypted through `TF_ENCRYPTION`, with the key provider `openbao` on the workspace's transit key (105) and `enforced = true` for state and plan.
8. **Stale lock recovery.** `unlock ws-<id>` takes the Sales Order and line. It refuses while a `provision` or `destroy` task of that workspace is running, and otherwise runs `tofu force-unlock -force` with the lock id read from the `.tflock` object.

Rejected:

- Semaphore's native OpenTofu app: it runs the `.tf` files of the repository checkout (103).
- Provisioning on the workspace runner: the unscoped tokens and the DNS token would reach code a member can change.
- HCL `.tfvars`: JSON is checked by the same schema the store uses.

## Open Decision: The Deploy Zone

Store decision 18 puts the per-deploy records in "a subzone of `infinito.nexus` on Cloudflare". A token that can write those records can write every record of the zone they live in.

| Option | What it means | Risk |
| --- | --- | --- |
| A | A registered domain of its own (for example `<name>.cloud`) as a Cloudflare zone for deploy records only, with a token scoped to that zone. | A leaked token reaches deploy records only. One more domain to register. |
| B | `<sub>.infinito.nexus` as a Cloudflare subdomain zone with a token scoped to it. | As A; needs the Enterprise plan. |
| C | The records in the `infinito.nexus` zone, the token readable only by the provision runner. | A leaked token can rewrite every record of `infinito.nexus`, the store's and the platform's included. |

Recommendation: **A**. It isolates as well as B without the Enterprise plan, and C is the least secure. The criteria below hold for each option. Only the zone name and the token's scope change.

## Acceptance Criteria

### Image

- [ ] The provision runner image reports one pinned OpenTofu of at least 1.10.0, and a build whose archive sum differs from the pinned one fails (`test_the_build_pins_and_verifies_opentofu` in `tests/unit/python/roles/web-app-semaphore/test_runner_build.py`; `provision runner: tofu reports the pinned version` in `roles/web-app-semaphore/files/playwright/test-provision.js`).
- [ ] The image build runs `tofu init -backend=false` and `tofu validate` for every root module in a build stage without network, so a root that needs a download or does not validate fails the build. The CLI configuration names only the mirror (`test_the_build_initialises_every_root_offline` and `test_the_cli_config_installs_from_the_mirror_only` in `tests/unit/python/roles/web-app-semaphore/test_runner_build.py`; the build step's output in the deploy log of the final IAM roundtrip).
- [ ] A root whose lock file names a provider the mirror lacks fails the image build, not a task (`test_a_provider_missing_from_the_mirror_fails_the_build` in `tests/unit/python/roles/web-app-semaphore/test_runner_build.py`).

### Root modules

- [ ] `roots/` holds exactly `hetzner`, `ionos`, `scs`, `proxmox` and `incus`. The `variable` and `output` blocks of each equal the inputs and outputs of `interface.json`, and each pins every provider to an exact version with a lock file. Negative controls drop an output, add a variable and loosen a pin (`test_every_root_implements_the_interface` and its controls in `tests/lint/repository/opentofu/test_root_modules.py`).
- [ ] Each root creates its DNS record through `modules/dns-cloudflare`, and no root declares a `cloudflare` resource of its own (`test_every_root_uses_the_dns_module` in `tests/lint/repository/opentofu/test_root_modules.py`).
- [ ] A provision of the `incus` root against the Incus e2e target (109) and of the `proxmox` root against the Proxmox test target (110) returns all four outputs. A destroy afterwards leaves neither the server nor its DNS record (`provision: incus creates and destroys a server` and `provision: proxmox creates and destroys a server` in `test-provision.js`). The hosted providers' roots run in the store's lanes against their fakes and test accounts (store criterion 062:132).

### Values only

- [ ] The provision script refuses a checkout that holds any of the six refused file kinds, one case each, and runs a clean one (`test_provision_refuses_infrastructure_code_in_the_checkout` in `tests/unit/python/roles/web-app-semaphore/files/test_provision_sh.py`).
- [ ] The provision script refuses a tfvars file with an unknown key, a wrong type, an unknown size or region, and an HCL file in place of JSON, one case each (`test_provision_refuses_each_malformed_tfvars` in `test_provision_sh.py`).
- [ ] OpenTofu runs in a copy of the image's root module inside the task directory, and a `TF_CLI_ARGS` or `TF_VAR_*` from the environment does not reach it (`test_provision_runs_the_image_module_with_a_clean_tf_env` in `test_provision_sh.py`).

### State

- [ ] The backend configuration the script writes names the workspace bucket, the key `<sales order>/<line>.tfstate` and `use_lockfile = true`. The key has no run id, and a Sales Order or line outside `[A-Za-z0-9-]` is refused (`test_the_state_key_is_sales_order_and_line` in `test_provision_sh.py`).
- [ ] The state object in the bucket is OpenTofu's encrypted envelope, never plaintext state. Reading it with another workspace's transit key fails (`provision: the state is encrypted with the workspace key` in `test-provision.js`).
- [ ] With `enforced = true`, a run whose OpenBao login fails writes no state and exits non-zero (`provision: no unencrypted state without the key` in `test-provision.js`).
- [ ] Two `provision` tasks for the same Sales Order and line at the same time end with one server. The second waits for the lock or fails on it, and never applies alongside the first (`provision: a second writer waits for the lock` in `test-provision.js`; the S3 side is 108).
- [ ] `unlock ws-<id>` removes a lock that no running task holds, and refuses while a `provision` task of the workspace runs (`provision: unlock clears only a stale lock` in `test-provision.js`).

### Isolation

- [ ] A workspace runner holds no provider token, no DNS token and no S3 identity: a probe task in a workspace project finds none in its environment and gets 403 from OpenBao on the provision paths (`provision isolation: a workspace task reads no provision secret` in `test-provision.js`).
- [ ] The DNS token is scoped to the zone the operator picked, and a write outside it answers 403 (`provision: the DNS token writes only its zone` in `test-provision.js`).

### Documentation

- [ ] The [README](../../roles/web-app-semaphore/README.md) documents the provision project, the interface, the refused files, the state key, the encryption, the unlock template and the deploy zone (`test_the_readme_names_the_provision_contract` in `tests/unit/python/roles/web-app-semaphore/test_readme.py`).
