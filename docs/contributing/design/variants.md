# Variants 🧬

How the development deploy CLI consumes per-role `meta/variants.yml` and iterates the resulting matrix at deploy time.
For general documentation rules such as links, writing style, RFC 2119 keywords, and Sphinx behavior, see [documentation.md](../documentation.md).
For the file format itself see [variants.md](../artefact/files/role/variants.md).
For how a single round's inventory is assembled (the layer this matrix wrapper sits on top of), see [inventory.md](inventory.md).
For the contributor-facing make target / dev-CLI workflow see [deploy.md](../actions/deploy.md).

## Folder-per-round model 🎛️

The development deploy CLI uses a **folder-per-round model** that splits cleanly between the init step (which materialises the inventories) and the deploy step (which iterates them):

1. **Round count.** `total_rounds = max(variant_count for app in primary_apps)`. If every primary app has only one variant, both steps degrade to a single folder and the unsuffixed inventory path is used.
2. **Per-round variant selection.** In round R every primary app uses variant index `R if R < its_variant_count else 0`. So a single-variant app stays on variant 0 in every round, and a 3-variant app in a 5-round deploy follows `0, 1, 2, 0, 0`.
3. **Inventory folders.** [init.py](../../../cli/administration/deploy/development/init.py) calls [build_dev_inventory_matrix](../../../cli/administration/deploy/development/inventory/builder.py), which creates one folder per round at `<inventory-dir>-<round>` (or just `<inventory-dir>` when there is a single round). For each folder, `build_dev_inventory` resolves the round's per-app variant payload and bakes it into the inventory's `host_vars` as `applications.<app>: <variant-payload>` overrides. The inventory is therefore variant-resolved on disk; no runtime selector is needed.
4. **Deploy iteration.** [deploy.py](../../../cli/administration/deploy/development/deploy.py) re-derives the same plan via `plan_dev_inventory_matrix` (the planner is a pure function shared between init and deploy) and runs one deploy per folder. **Every round deploys its full variant-aware include set.** Round R starts from a clean host (the previous round's include is purged before round R begins, see point 5), so every dep that round R needs MUST be redeployed.
5. **Cleanup between rounds.** Before each non-first iteration the wrapper runs [entity.sh](../../../scripts/tests/deploy/local/purge/entity.sh) for **every** app in the previous round's include set. The next round therefore boots from an empty host, which guarantees cross-round state coherence: nothing the previous round deployed (whether it stays in the current round's closure or falls out) can leak into round R, so variants are free to disagree on which deps they pull in. The final round is followed by no purge so the last state remains available for inspection or follow-up specs.
6. **`--full-cycle` (async update pass).** When set (or `full_cycle=true` on `make compose-deploy`), the wrapper runs each round's deploy TWICE: first the regular sync pass, then immediately a second pass with `-e ASYNC_ENABLED=true` overriding the host_var, against the SAME variant's folder, BEFORE moving to the next round. The two passes are therefore always co-located on the same host state; the async pass never accidentally targets a host that a previous round's variant left behind.
7. **Pinning to a single round.** Both init and deploy accept `--variant <idx>` (same semantics as the `variant=` make arg) to pin operations to a single round's folder. In single-round mode no inter-round cleanup runs, since there is no previous round to diff against. The `make compose-deploy mode=update` flows honour the same `variant=` arg by suffixing `INFINITO_INVENTORY_DIR` / `INFINITO_INVENTORY_FILE` to `<base>-<idx>`, so a redeploy can target one specific variant without iterating the full matrix.

The in-play loader (`utils.cache.applications.get_merged_applications`) uses each role's variant-free base config (the assembled `meta/<topic>.yml` payload) as the default and lets the inventory's `applications.<app>` overrides win via deep merge: the inventory itself is the source of truth for what variant a round runs against. Variant 0 enumerates every dynamic service-key from `meta/services.yml` with `enabled: true, shared: true` so the "all flags on" baseline is explicit and deep-merge with a non-baseline override yields the expected variant-N shape (see [variants.md](../artefact/files/role/variants.md) for the file-format rule and [test_non_baseline_explicit_disables.py](../../../tests/integration/roles/meta/variants/test_non_baseline_explicit_disables.py) for the lint guard).

## Credentials Generation 🔐

Credential generation participates in the matrix model so the shared providers a variant actually pulls in (via `services.<key>.enabled+shared`) receive their schema-defined credentials in the inventory before deploy time.

### CI/CD Path 🤖

The dev-deploy CLI threads the variant index through three layers so a variant's `variants.yml` overlay reaches the credential subprocess.

1. `build_dev_inventory` reads `spec.variant_selectors()` from the planner.
   When the round pins any variant, it appends `--app-variants <JSON>` to the `infinito administration inventory provision` invocation with the per-app `{app_id: variant_index}` mapping.
2. The provision CLI parses the JSON and forwards the per-app index as `--variant <N>` to each `infinito administration inventory credentials` subprocess call.
3. `InventoryManager` resolves the root role's config via `get_variants(roles_dir)[app_id][N]` so `resolve_schema_includes_recursive` sees the variant-merged `services` map and discovers every shared provider the variant enables.

The resulting snippets cover every shared provider in the variant's closure, so the deploy stage finds the required `applications.<provider>.credentials` block in the inventory and `lookup('config', 'credentials', '<provider>')` succeeds.

The variant only affects inventory generation; the Ansible deploy itself reads `applications.<app>` overrides from the variant-resolved inventory and MUST NOT consult variant data at runtime.

### Standalone Path 🖥️

Direct callers that do not run the matrix planner (manual `infinito administration inventory provision`, ad-hoc credential refresh, `make compose-up`) omit `--app-variants` / `--variant`.

The CLIs default `variant` to `None` so:

1. `InventoryManager` skips the variants overlay and reads the role's base `meta/<topic>.yml` payload directly via `_meta_role_config`.
2. Shared-provider discovery sees only what the base config enables.
3. Generated credentials cover the base config only.

Apps without a `meta/variants.yml` file collapse to a single empty overlay in `_load_variants_overrides`, so `--variant 0` and the standalone path produce identical credential snippets for them.

## What not to do 🚫

- You MUST NOT introduce a parallel cache. The variants are cached per `roles_dir` inside `utils/cache/applications.py` and returned as deep copies; mutating the result MUST NOT corrupt subsequent lookups.
- You MUST NOT skip the inter-round purge.
- You MUST NOT introduce a runtime variant-selector extra-var. Variant data lives in the inventory after init; the deploy stage reads it as plain `applications.<app>` overrides.

## Reference files 📌

| File | Purpose |
|---|---|
| [variants.md](../artefact/files/role/variants.md) | File-structure rules for `roles/<role>/meta/variants.yml`. |
| [applications.py (cache)](../../../utils/cache/applications.py) | Loader and cache for `_build_variants` (`get_variants` is the public Python entry point). The merged-applications path stays variant-agnostic; variant payloads reach it as inventory-level `applications.<app>` overrides. |
| [inventory/](../../../cli/administration/deploy/development/inventory/__init__.py) | Dev inventory build package. Per-submodule split: [`spec.py`](../../../cli/administration/deploy/development/inventory/spec.py) (`DevInventorySpec`), [`builder.py`](../../../cli/administration/deploy/development/inventory/builder.py) (`build_dev_inventory` variant baking + `build_dev_inventory_matrix` per-round driver), [`planner.py`](../../../cli/administration/deploy/development/inventory/planner.py) (`plan_dev_inventory_matrix` pure planner shared with the deploy wrapper), [`legacy_resolver.py`](../../../cli/administration/deploy/development/inventory/legacy_resolver.py) (`CombinedResolver`-driven include resolution). |
| [init.py](../../../cli/administration/deploy/development/init.py) | Dev CLI entry that drives `build_dev_inventory_matrix` to materialise `<inventory-dir>-<round>` folders. |
| [deploy.py](../../../cli/administration/deploy/development/deploy.py) | Dev CLI entry that re-derives the matrix plan and iterates one deploy per folder, with per-app cleanup between rounds. |
| [entity.sh](../../../scripts/tests/deploy/local/purge/entity.sh) | Cleanup script invoked between rounds for every app in the previous round's include set. |
| [test_variants.py](../../../tests/unit/utils/cache/test_variants.py) | Unit tests covering parser edge cases, deep-merge semantics, caching, and the variant-zero default path. |
| [tests/.../inventory/](../../../tests/unit/cli/administration/deploy/development/inventory/__init__.py) | Unit-test package mirroring the source split: [`test_spec.py`](../../../tests/unit/cli/administration/deploy/development/inventory/test_spec.py), [`test_payload.py`](../../../tests/unit/cli/administration/deploy/development/inventory/test_payload.py), [`test_planner.py`](../../../tests/unit/cli/administration/deploy/development/inventory/test_planner.py), [`test_builder.py`](../../../tests/unit/cli/administration/deploy/development/inventory/test_builder.py). |
| [test_matrix_deploy.py](../../../tests/unit/cli/administration/deploy/development/test_matrix_deploy.py) | Wrapper-level tests covering the per-round folder iteration and cleanup logic. |
| [cli.py (provision)](../../../cli/administration/inventory/provision/cli.py) | Parses `--app-variants <JSON>` and forwards the per-app variant index to `generate_credentials_for_roles`. |
| [credentials_generator.py](../../../cli/administration/inventory/provision/credentials_generator.py) | Issues one credentials subprocess per app, appending `--variant <N>` when the app's variant is set. |
| [credentials/](../../../cli/administration/inventory/credentials/__main__.py) | `InventoryManager`-backed credential generator; `--variant N` selects which `variants.yml` overlay applies. |
| [InventoryManager](../../../utils/manager/inventory.py) | Loads the root role's variant-merged config via `get_variants` when `variant` is an integer; default `variant=None` keeps the standalone path on base meta only. |
