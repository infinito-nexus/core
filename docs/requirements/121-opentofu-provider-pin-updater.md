# 121 - OpenTofu Provider Pin Updater

## User Story

As a maintainer of core's OpenTofu root modules, I want the scheduled version update to bump every provider pin in the `*.tf.json` files and to regenerate the lock files with them, so that the providers of the runner image stay current through the same reviewed pull requests as every other pin of core.

## Background

The store's root modules pin their providers in `versions.tf.json` (core sidetree `feature/iam-reqs/062-tofu-root-modules`, commit `286b3689f1`). The store asked on 2026-11-13, as item (f) of its OpenTofu follow-ups, for an updater that sees them; the operator took it the same day.

### Today

- Each root pins every provider to an exact version and carries its lock file, and the runner build mirrors the providers the lock files name ([104](104-runner-image-opentofu-and-root-modules.md) decisions 2 and 3).
- Core bumps its own pins in the scheduled workflow `🔄 Update versions` (`.github/workflows/cron-update.yml`): one job per pin kind runs a thin shim under `scripts/github/update/`, which calls a CLI under `cli/contributing/update/`, and opens a pull request through `scripts/github/update/open/`. The jobs run only when `CI_ENABLE_AUTO_UPDATES` is `true` (`scripts/github/update/README.md`), and every role-scoped updater skips a role whose lifecycle is `eol` (`cli/contributing/update/README.md`).
- `.github/dependabot.yml` enables neither the `terraform` nor the `opentofu` ecosystem.

### Upstream

| Fact | Source |
| --- | --- |
| Dependabot's `terraform` ecosystem reads `.tf` and `.hcl` files, its `opentofu` ecosystem `.tf`, `.tofu` and `.hcl` files; neither reads `.tf.json`. | [terraform file_fetcher.rb:23-24,56](https://github.com/dependabot/dependabot-core/blob/1233a4d6231766ac3bded34aac405d82a037bf59/terraform/lib/dependabot/terraform/file_fetcher.rb#L23-L56), [opentofu file_fetcher.rb:23-24,56](https://github.com/dependabot/dependabot-core/blob/1233a4d6231766ac3bded34aac405d82a037bf59/opentofu/lib/dependabot/opentofu/file_fetcher.rb#L23-L56) |
| The OpenTofu registry lists a provider's releases at `/v1/providers/<namespace>/<type>/versions`. | [Provider registry protocol](https://opentofu.org/docs/internals/provider-registry-protocol/) |
| `tofu providers lock` writes the lock file with the checksums of every `-platform` it is given. | [tofu providers lock](https://opentofu.org/docs/cli/commands/providers/lock/) |

## Decisions

1. **A core updater for `*.tf.json` (operator pick, 2026-11-13).** `python -m cli.contributing.update.opentofu`, with its logic in `utils/update/opentofu.py`, scans every `versions.tf.json` under `roles/*/files/opentofu/`. For each provider it asks the OpenTofu registry for the newest release that is not a pre-release (Upstream), and sets that exact version in every file that pins the provider, so all roots of a core tag share one version per provider. It honours `--dry-run` and skips a role whose lifecycle is `eol`, like the other updaters.
2. **Lock files follow the pins.** For every root whose pins changed, the updater runs `tofu providers lock` with the pinned OpenTofu of 104 decision 2 and one `-platform` per platform the runner image is built for, so the build's mirror finds every checksum it needs.
3. **The same pipeline.** The shim `scripts/github/update/opentofu_pins.sh` runs it, and the job `update-opentofu-pins` of `cron-update.yml` opens a pull request through `scripts/github/update/open/role_prs.sh roles`, behind the same `CI_ENABLE_AUTO_UPDATES` gate. The pull request's CI builds the runner image, whose offline `tofu init` and `tofu validate` of every root (104) fail a bump that breaks one. `tests/external/update/opentofu/` warns about pending bumps, as the other external update tests do.

Rejected:

- Rewriting the pins as HCL `versions.tf` for Dependabot: one root would mix two formats, and its provider bumps would leave core's own update pipeline, which already carries images, pip, collections and refs.
- Pins per root without a shared version: two roots of one image would mirror two releases of one provider.

## Acceptance Criteria

- [x] Against a fake registry, the updater bumps every `versions.tf.json` that pins a provider to the newest release, ignores a pre-release, leaves an `eol` role untouched and writes nothing under `--dry-run`; each case has its own test (`test_the_opentofu_updater_bumps_every_pin`, `test_a_pre_release_is_ignored`, `test_an_eol_role_is_untouched` and `test_a_dry_run_writes_nothing` in `tests/unit/python/utils/update/test_opentofu.py`, 8 tests green at the lane tip, over `utils/update/opentofu.py` and `cli/contributing/update/opentofu/__main__.py`; the planted regressions that take a pre-release, bump an `eol` role or write under `--dry-run` fail their case).
- [x] After a bump, a `tofu` shim records one `providers lock` per changed root with one `-platform` per runner image platform; a negative control without the lock step leaves the lock file stale and must fail (`test_the_lock_files_follow_the_pins` and `test_negative_control_without_the_lock_step_the_lock_is_stale` in `test_opentofu.py`; the planted regressions that skip the lock step or lock one platform only fail the first, and `test_an_archive_off_its_pin_is_refused` refuses an OpenTofu archive off its pinned sum).
- [x] `cron-update.yml` holds the job `update-opentofu-pins`, gated on `CI_ENABLE_AUTO_UPDATES`, which runs `scripts/github/update/opentofu_pins.sh` and opens its pull request through `open/role_prs.sh` (`test_the_update_workflow_runs_the_opentofu_updater` in `tests/unit/python/scripts/github/update/test_opentofu_pins.py`, green at the lane tip; the planted ungated job fails it).
- [ ] `tests/external/update/opentofu/` warns, without failing, about every provider pin behind the registry (`test_opentofu_provider_pins` in `tests/external/update/opentofu/test_opentofu_pins.py`).
- [x] The [update README](../../cli/contributing/update/README.md) documents the updater, its file scope and the lock step (`test_the_update_readme_names_the_opentofu_updater` in `tests/unit/python/utils/update/test_opentofu.py`, green at the lane tip).
