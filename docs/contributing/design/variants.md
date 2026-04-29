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
3. **Inventory folders.** [init.py](../../../cli/deploy/development/init.py) calls [build_dev_inventory_matrix](../../../cli/deploy/development/inventory.py), which creates one folder per round at `<inventory-dir>-<round>` (or just `<inventory-dir>` when there is a single round). For each folder, `build_dev_inventory` resolves the round's per-app variant payload and bakes it into the inventory's `host_vars` as `applications.<app>: <variant-payload>` overrides. The inventory is therefore variant-resolved on disk; no runtime selector is needed.
4. **Deploy iteration.** [deploy.py](../../../cli/deploy/development/deploy.py) re-derives the same plan via `plan_dev_inventory_matrix` (the planner is a pure function shared between init and deploy) and runs one deploy per folder. **Round 0 deploys the full include set** (the baseline state, including dependencies). **Rounds R>0 only re-deploy apps that have a real variant for that round** (i.e. `round_variants[app] == R`); apps that would only fall back to variant 0 are left at whatever state the previous round produced. This is the user-facing default: if variant 1 only exists for WordPress, round 1 re-deploys WordPress alone, not Keycloak or other dependencies. A round in which no app has a real variant is skipped entirely.
5. **Cleanup between rounds.** Before each non-first iteration the wrapper runs [entity.sh](../../../scripts/tests/deploy/local/purge/entity.sh) for the apps that are **both** about to be re-deployed in this round AND whose variant changed since the previous round. Apps that are not being re-deployed are NOT purged: their previous-round state stays. The final round is followed by no purge so the last state remains available for inspection or follow-up specs.
6. **`--full-cycle` (async update pass).** When set (or `FULL_CYCLE=true` in the environment), the wrapper runs each round's deploy TWICE: first the regular sync pass, then immediately a second pass with `-e ASYNC_ENABLED=true` overriding the host_var, against the SAME variant's folder, BEFORE moving to the next round. The two passes are therefore always co-located on the same host state; the async pass never accidentally targets a host that a previous round's variant left behind.
7. **Pinning to a single round.** Both init and deploy accept `--variant <idx>` (or read the `VARIANT` environment variable) to pin operations to a single round's folder. In single-round mode no inter-round cleanup runs, since there is no previous round to diff against. The `make deploy-reuse-*` targets honour the same `VARIANT` env-var by suffixing `INVENTORY_DIR` / `INVENTORY_FILE` to `<base>-<idx>`, so a redeploy can target one specific variant without iterating the full matrix.

The in-play loader (`utils.cache.applications.get_merged_applications`) always uses variant 0 as the default and lets the inventory's `applications.<app>` overrides win via deep merge: the inventory itself is the source of truth for what variant a round runs against.

## What not to do 🚫

- You MUST NOT introduce a parallel cache. The variants are cached per `roles_dir` inside `utils/cache/applications.py` and returned as deep copies; mutating the result MUST NOT corrupt subsequent lookups.
- You MUST NOT skip the inter-round purge.
- You MUST NOT introduce a runtime variant-selector extra-var. Variant data lives in the inventory after init; the deploy stage reads it as plain `applications.<app>` overrides.

## Reference files 📌

| File | Purpose |
|---|---|
| [variants.md](../artefact/files/role/variants.md) | File-structure rules for `roles/<role>/meta/variants.yml`. |
| [applications.py (cache)](../../../utils/cache/applications.py) | Loader and cache for `_build_variants` (`get_variants` is the public Python entry point). The merged-applications path stays variant-agnostic; variant payloads reach it as inventory-level `applications.<app>` overrides. |
| [inventory.py](../../../cli/deploy/development/inventory.py) | Dev inventory build: `DevInventorySpec`, `build_dev_inventory` (variant baking), `plan_dev_inventory_matrix` (pure planner shared with the deploy wrapper), `build_dev_inventory_matrix` (creates one folder per round). |
| [init.py](../../../cli/deploy/development/init.py) | Dev CLI entry that drives `build_dev_inventory_matrix` to materialise `<inventory-dir>-<round>` folders. |
| [deploy.py](../../../cli/deploy/development/deploy.py) | Dev CLI entry that re-derives the matrix plan and iterates one deploy per folder, with per-app cleanup between rounds. |
| [entity.sh](../../../scripts/tests/deploy/local/purge/entity.sh) | Cleanup script invoked between rounds for every app whose variant changed. |
| [test_variants.py](../../../tests/unit/utils/cache/test_variants.py) | Unit tests covering parser edge cases, deep-merge semantics, caching, and the variant-zero default path. |
| [test_inventory.py](../../../tests/unit/cli/deploy/development/test_inventory.py) | Unit tests covering the planner, variant baking, and the per-folder build flow. |
| [test_matrix_deploy.py](../../../tests/unit/cli/deploy/development/test_matrix_deploy.py) | Wrapper-level tests covering the per-round folder iteration and cleanup logic. |
