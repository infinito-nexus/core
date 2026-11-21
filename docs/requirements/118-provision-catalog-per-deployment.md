# 118 - Provision Catalog per Deployment

## User Story

As the operator of a deployment that sells servers at several providers, I want to set the catalog of sizes and regions each root module maps to provider settings in my inventory, with core shipping only defaults its tests have proven, so that an order never maps to a server type or location nobody checked and I change my offer without a new runner image.

## Background

The store's root modules (`interface.json`, `$defs.catalog`, and one `catalog.json` beside each root, in the store's core sidetree `feature/iam-reqs/062-tofu-root-modules`, commit `286b3689f1`) carry default catalogs whose hosted-provider entries nobody has verified. The store asked on 2026-11-13, as item (c) of its OpenTofu follow-ups, that each deployment set its own; the operator took it the same day.

### Today

- A root maps the `size` and `region` of an order to provider settings "from the catalog", and the provision script refuses a size or region outside it ([104](104-runner-image-opentofu-and-root-modules.md) decisions 4 and 6). 104 does not say where the catalog lives.
- The root modules sit in the runner image of a core tag (104 decision 3), which every deployment of that tag shares.
- Hetzner, IONOS and SCS have no test account yet; Incus and Proxmox run against real targets (store decision 18, [109](109-incus-api-listener-and-project-per-workspace.md), [110](110-proxmox-test-target-and-pool-token-per-workspace.md)).

## Decisions

1. **One catalog per provider and deployment.** `services.semaphore.workspaces.catalog.<provider>` in `roles/web-app-semaphore/meta/services.yml` holds the catalog of each root in the shape of `$defs.catalog`. An inventory replaces a provider's catalog as a whole; core merges no entries into it. It is the only catalog: no `catalog.json` ships beside a root in the image.
2. **Only proven defaults.** The defaults of `incus` and `proxmox` are the sizes and regions the live provision tests of 109 and 110 run with, the template ids of [116](116-proxmox-vms-from-kvm-and-emulated-templates.md) included. The defaults of `hetzner`, `ionos` and `scs` are empty until a test account proves their server types and locations. A provision against an empty catalog refuses and names the provider.
3. **Checked at deploy, read at run time.** The deploy validates every effective catalog against `$defs.catalog` and fails naming the provider and the key. It writes each into a read-only mount of the provision runner. The provision script copies the provider's file from that mount beside the root in the task directory, and reads no catalog from the image or from the workspace checkout.

Rejected:

- Defaults for providers without a test account: a size could map to a server type other than the one the store sells.
- The catalog in the workspace repository: a member could map an order to a larger server.
- The catalog only in the image: a deployment could change its offer only with a new image.

## Acceptance Criteria

- [x] The default catalogs of `incus` and `proxmox` are non-empty and valid against `$defs.catalog`, and those of `hetzner`, `ionos` and `scs` are empty (`test_only_proven_catalogs_have_defaults` in `tests/unit/python/roles/web-app-semaphore/test_catalog.py`, 5 tests green at the lane tip, over `services.semaphore.workspaces.catalog` in `roles/web-app-semaphore/meta/services.yml`).
- [x] An inventory catalog for one provider replaces its default as a whole, and one that breaks `$defs.catalog` fails the deploy with the provider and key in the message, one case per rule of the schema (`test_an_inventory_catalog_replaces_the_default` and `test_an_invalid_catalog_fails_the_deploy` in `test_catalog.py`, through `semaphore_catalogs` in `roles/web-app-semaphore/filter_plugins/semaphore_catalog.py` read by `SEMAPHORE_WORKSPACE_CATALOGS` in `roles/web-app-semaphore/vars/main.yml`; the planted regressions that merge instead of replace, skip the check or ignore a schema keyword fail them).
- [x] The provision runner mounts the catalogs read-only, and the provision script uses the mounted file: a `catalog.json` planted in the checkout or beside the image's root changes nothing, and a provision against an empty catalog refuses naming the provider (`test_provision_reads_the_mounted_catalog_only` in `tests/unit/python/roles/web-app-semaphore/files/test_provision_sh.py`, 35 tests green; the mount `semaphore_provision_catalogs` in `roles/web-app-semaphore/meta/volumes.yml` renders read-only into `provision-runner` only and `PROVISION_CATALOG_DIR` is its target, `test_the_catalogs_mount_read_only_into_the_provision_runner_only` and `test_the_catalog_dir_of_the_script_is_the_mount_target` in `tests/unit/python/roles/web-app-semaphore/test_provision_environment.py`, 11 tests green; the planted writable mount and the mount moved to `export-runner` fail it).
- [x] The [README](../../roles/web-app-semaphore/README.md) documents the catalog key, its shape, which defaults are proven and that hosted providers need a deployment catalog (`roles/web-app-semaphore/README.md`).
