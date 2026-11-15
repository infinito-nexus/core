# 129 - Custom Roles Manifest: Public Custom Roles Every Checkout Carries

## User Story

As a maintainer of Infinito.Nexus core, I want a root manifest that pins the public custom roles (`web-app-cst-*`) by release tag and commit, so that every core checkout pulls them before `make test`, in CI and before every deploy, and their roles, tests and service providers are always loaded without an inventory declaring them.

## Context (2026-11-13, base baa2dfef43)

- [046](046-custom-roles.md) pulls a custom role only when an inventory declares it under `applications.web-app-cst-<name>.source`. `make test`, `make lint` and CI run without such an inventory, so they never see a custom role, and an in-tree role that consumes a custom role's service provider cannot be tested.
- The first public custom role core depends on is `web-app-cst-cosmos` from [cosmos](https://github.com/kevinveenbirkenbach/cosmos). Its repository also carries a tag `latest` that moves on every release.
- The version updaters live in [cli/contributing/update/](../../cli/contributing/update/README.md) and run from [cron-update.yml](../../.github/workflows/cron-update.yml).

## Decisions (operator, 2026-11-13)

Binding; not reopened by this document.

| # | Decision |
|---|---|
| D1 | `meta/custom_roles.yml` is a YAML map with one key per role. Each entry holds the fields of the 046 `source` (`url`, `version` as a tag, `path`) and `commit`, the full 40-hex commit the tag must resolve to. A tag that resolves to another commit stops the run with a message naming the role and both commits, like `pip --hash`. A branch as `version` stays refused as in 046. |
| D2 | Only public repositories go in: an `https` URL without credentials. Private roles (brand, team, store) stay inventory-only. What is checkable offline is enforced, the rest is documented. |
| D3 | The manifest is the default; an inventory pin `applications.web-app-cst-<name>.source` of the same role overrides it for that host. |
| D4 | An updater bumps `version` to the newest non-prerelease semver tag and `commit` to the commit that tag resolves to, integrated into `cli/contributing/update/` and `cron-update.yml` like the existing updaters. |
| D5 | Initial content: exactly one entry, `web-app-cst-cosmos` at `v0.2.0`, commit `b568fde4da3c340163628c37e89e0ef73d6eaf1e` (annotated tag, peeled commit), path `ansible/roles/web-app-cst-cosmos`. |
| D6 | `latest` and every other tag that is no `vX.Y.Z` or `X.Y.Z` release is refused as `version`. The updater picks only such release tags, never `latest` or a prerelease, and always writes the peeled commit of the tag. |

## Approach

### Manifest

```yaml
web-app-cst-cosmos:
  url: https://github.com/kevinveenbirkenbach/cosmos.git
  version: v0.2.1
  commit: 5071beca9cfb32f22fab6973548931f29fae013f
  path: ansible/roles/web-app-cst-cosmos
```

The pin moved from the initial `v0.2.0` (D5) to `v0.2.1` (2026-11-14, Cosmos release 18:45: production lint fix, library source `cosmos.mjs`, CDN path `js/cosmos.js` and embeds unchanged).

[manifest.py](../../cli/administration/roles/manifest.py) validates each entry with the parser of 046 ([declaration.py](../../cli/administration/roles/declaration.py), `parse_source`: unknown fields, Jinja and tagged values, credentials, path naming the group, entity collisions) and adds the manifest's own limits: the `web-app-cst-` prefix, a public `https` URL, a release tag as `version` and a full commit as `commit`. Every check runs offline, before anything is fetched. Whether `version` names a branch or a tag is only known online; that check stays the 046 `git ls-remote` check of [source.py](../../cli/administration/roles/source.py). The fetch compares the commit the tag peels to with `commit` before it unpacks anything.

### Pull

| Call | Places | Removes |
|---|---|---|
| with an inventory (`deploy dedicated`, `deploy swarm`, `make roles-pull inventory=...`) | every pinned role, an inventory `source` replacing the pin of its role, and every role the inventory declares | every placed role neither declares |
| without an inventory or with an inline host list (`make roles-pull`, `make test`, `make lint`, `development up`) | every pinned role that is missing or was placed from another pin | nothing; a role an inventory placed stays, an inventory override of a pinned role included |

A role placed from the manifest records `pinned by meta/custom_roles.yml` in the `source` line of its marker, so a pull without an inventory tells a current pin (kept without any network access), an older pin (replaced) and an inventory placement (kept) apart. A pinned group needs neither `custom: true` nor a `source` in the inventory; a host joins it like any other group, and a `source` alone overrides the pin.

### Hooks

| Path | Hook |
|---|---|
| `make test`, `make lint`, CI `call-test.yml` and `call-lint.yml` | `roles-pull` is a prerequisite of `test` and `lint`; `roles-pull` depends on `install` |
| `make compose-up`, every `make compose-deploy` flow, the CI compose deploy | `cli.administration.deploy.development up` pulls before the stack starts |
| CI swarm deploy | the `📥 Pull the pinned custom roles` step of `call-test-deploy.yml` runs `make roles-pull` after the host venv install |
| `infinito administration deploy dedicated` and `deploy swarm` | the existing 046 pull, which now merges the manifest |

### Updater

[custom_roles.py](../../utils/update/custom_roles.py) reads the manifest, lists the tags of each repository with `git ls-remote --tags` ([repository.py](../../utils/update/repository.py), `git_ls_remote_tag_commits`, which maps an annotated tag to its `^{}` commit), picks the highest `vX.Y.Z` or `X.Y.Z` tag above the pin and rewrites `version` and `commit` of that entry only. The `update-custom-roles` job of `cron-update.yml` runs it through [custom_roles.sh](../../scripts/github/update/custom_roles.sh) and opens one PR for `meta/custom_roles.yml`.

## Acceptance Criteria

Proof tiers: `[unit]` a unit test or lint, `[ci]` a CI run, `[host]` the operator's workstation.

### Manifest

- [x] `meta/custom_roles.yml` exists, maps `web-app-cst-cosmos` to `url` `https://github.com/kevinveenbirkenbach/cosmos.git`, `version` `v0.2.1`, `commit` `5071beca9cfb32f22fab6973548931f29fae013f` and `path` `ansible/roles/web-app-cst-cosmos`, and passes its own validation. `[unit]` (`tests/unit/python/cli/administration/roles/test_manifest.py`: `test_checked_in_manifest_is_valid`.)
- [x] An entry that misses `url`, `version`, `commit` or `path` stops the run before anything is fetched, and the message names the role and the field. `[unit]` (`tests/unit/python/cli/administration/roles/test_manifest.py`: `test_missing_field_names_role_and_field`, one subtest per field, with `test_valid_entry_is_read_with_its_commit` as the negative control.)
- [x] An entry whose `url` embeds credentials stops the run without echoing the URL; an SSH, plain HTTP or local `url` stops the run naming the role. `[unit]` (`tests/unit/python/cli/administration/roles/test_manifest.py`: `test_url_with_credentials_is_refused_without_echoing_it`, `test_url_other_than_public_https_is_refused`.)
- [x] A `version` that is no release tag `vX.Y.Z` or `X.Y.Z`, such as `latest`, a prerelease, a branch name or a commit, stops the run naming the role and the value. `[unit]` (`tests/unit/python/cli/administration/roles/test_manifest.py`: `test_version_other_than_a_release_tag_is_refused`, with `test_release_tag_without_v_is_read` as the negative control; `test_placement_manifest.py`: `test_branch_as_version_is_refused`.)
- [x] A `version` that names a branch shaped like a release tag stops the pull through the `git ls-remote` check of 046, before `roles/` changes. `[unit]` (`tests/unit/python/cli/administration/roles/test_placement_manifest.py`: `test_branch_named_like_a_release_is_refused`.)
- [x] A `commit` that is no full 40-hex SHA stops the run naming the role. `[unit]` (`tests/unit/python/cli/administration/roles/test_manifest.py`: `test_short_commit_is_refused`, `test_jinja_is_refused`.)
- [x] A tag that resolves to a commit other than `commit` stops the pull with a message naming the role, the resolved and the pinned commit, and `roles/` stays unchanged; an annotated tag is compared by its peeled commit. `[unit]` (`tests/unit/python/cli/administration/roles/test_placement_manifest.py`: `test_tag_that_resolves_to_another_commit_stops_naming_both`, `test_annotated_tag_is_checked_against_its_peeled_commit`.)
- [x] The manifest validation reuses the 046 source parser; no check of 046 exists a second time. `[unit]` (`tests/unit/python/cli/administration/roles/test_manifest.py`: `TestManifestReusesTheSourceParser` asserts `parse_source`, `entity_collisions` and `embeds_credentials` are the 046 objects and no 046 message is restated in `manifest.py`; `test_unknown_field_is_refused`, `test_jinja_is_refused`, `test_path_naming_another_directory_is_refused` and `test_entity_name_of_an_in_tree_role_is_refused` show the 046 messages reach the manifest.)

### Precedence and pull

- [x] An inventory `source` of a pinned role replaces the pin for that inventory's pull, with or without `custom: true`. `[unit]` (`tests/unit/python/cli/administration/roles/test_placement_manifest.py`: `test_inventory_pin_overrides_the_manifest`, `test_source_without_custom_overrides_a_pinned_role`.)
- [x] A host joins a pinned group without `custom: true` and without a `source`, and gets the pinned role. `[unit]` (`tests/unit/python/cli/administration/roles/test_placement_manifest.py`: `test_pinned_group_needs_neither_custom_nor_source_in_the_inventory`.)
- [x] An inventory pull that does not declare a pinned role places it from the manifest and never removes it as undeclared. `[unit]` (`tests/unit/python/cli/administration/roles/test_placement_manifest.py`: `test_inventory_pull_places_the_pinned_role_it_does_not_declare`, `test_inventory_pull_restores_the_manifest_pin_after_an_override`.)
- [x] `make roles-pull` without `inventory` places every pinned role that is missing or placed from another pin, keeps a current pin without fetching, keeps an inventory override, and removes nothing. `[unit]` (`tests/unit/python/cli/administration/roles/test_placement_manifest.py`: `TestManifestPull` and `test_pull_without_an_inventory_keeps_the_override`; `tests/unit/python/cli/administration/roles/pull/test_command.py`: `test_without_an_inventory_only_the_manifest_is_pulled`.)

### Hooks

- [x] `make test` and `make lint` run `make roles-pull` before their suites. `[unit]` (`tests/unit/python/cli/administration/roles/pull/test_command.py`: `TestMakeTargetsPullFirst`.)
- [x] `cli.administration.deploy.development up` pulls the pinned roles before the stack starts, so `make compose-up`, `make compose-deploy` and the CI compose deploy carry them. `[unit]` (`tests/unit/python/cli/administration/deploy/development/test_up.py`: `test_pinned_custom_roles_are_pulled_before_the_stack_starts`, with `test_running_stack_is_left_without_a_pull` beside it.)
- [ ] The CI swarm deploy runs `make roles-pull` before the drill. `[ci]`
- [ ] A CI `make test` run on core shows `web-app-cst-cosmos` placed and its tests collected. `[ci]`

### Updater

- [x] `python -m cli.contributing.update.custom_roles` moves `version` to the newest release tag `vX.Y.Z` or `X.Y.Z` above the pin and `commit` to the commit that tag peels to, skipping `latest` and prereleases, and leaves every other entry unchanged. `[unit]` (`tests/unit/python/utils/update/test_custom_roles.py`: `test_the_module_writes_the_newest_release_and_its_peeled_commit`, `test_newest_release_tag_wins_over_latest_and_prereleases`, `test_annotated_tag_writes_its_peeled_commit`, `test_apply_rewrites_version_and_commit_of_that_role_only`.)
- [x] A current pin, a pin whose `version` is no release tag and a failed lookup leave the manifest unchanged. `[unit]` (`tests/unit/python/utils/update/test_custom_roles.py`: `test_current_pin_is_left_alone`, `test_moving_tag_as_pin_is_never_bumped`, `test_failed_lookup_leaves_the_pin`.)
- [ ] The `update-custom-roles` job of `cron-update.yml` runs the updater and opens a PR for `meta/custom_roles.yml` only. `[ci]`

### Documentation

- [x] [deploy.md](../administration/deploy.md) documents the manifest, its limits, the precedence, the pull without an inventory and the updater; the [updater README](../../cli/contributing/update/README.md) documents the updater. `[unit]` (`tests/unit/python/utils/update/test_custom_roles.py`: `TestCustomRolesDocumentation`.)

## Tests

- `tests/unit/python/cli/administration/roles/test_manifest.py`: the checked-in manifest, a valid entry, every missing field, credential, SSH, HTTP and local URLs, `latest`, prerelease, branch-shaped and commit versions, a short commit, unknown fields, Jinja, the prefix, the path name, entity collisions.
- `tests/unit/python/cli/administration/roles/test_placement_manifest.py`: the pull without an inventory, the inline host list, the peeled annotated tag, the tag-commit mismatch, both branch refusals, the current pin kept without fetching, the changed pin replaced, nothing removed, the inventory override with and without `custom: true` and its precedence, the pinned group without `custom: true`.
- `tests/unit/python/cli/administration/roles/pull/test_command.py`: the CLI without an inventory pulls the manifest only.
- `tests/unit/python/cli/administration/deploy/development/test_up.py`: `up` pulls before the stack starts.
- `tests/unit/python/utils/update/test_custom_roles.py`: a repository with `latest`, a prerelease, a lightweight and an annotated release tag; the newest release wins, its peeled commit is written, only its entry changes, a current pin, a `latest` pin and a failed lookup stay.

Every test builds throwaway local Git repositories in a temporary directory; none reaches the network. The pull tests keep the manifest's `https` URL and send it to the local repository through `url.<repository>.insteadOf` in the environment.

## Cross-linking

- Extends: [046 - Custom Roles from Inventory-Declared Sources](046-custom-roles.md).
