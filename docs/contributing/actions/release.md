# Release 🚀

Contributor guidance for cutting a tagged release of Infinito.Nexus.
For local-deploy and edit/redeploy guidance see [deploy.md](deploy.md).
For commit-message conventions see [commit.md](../artefact/git/commit.md).

## Versioning 🔢

Release tags follow [Semantic Versioning](https://semver.org/) with a leading `v`: `v<MAJOR>.<MINOR>.<PATCH>` (for example `v7.0.0`).

| Component | Bump when |
|---|---|
| `MAJOR` | A change is incompatible with prior inventories, on-disk role-meta layout, deploy CLI, or stored runtime state. |
| `MINOR` | New roles, new CLI surfaces, or a non-breaking schema extension lands. |
| `PATCH` | Bug fixes, doc fixes, or test-only changes that do not move public surface. |

Pre-release suffixes (`-rc1`, `-alpha2`, `+build.5`) MAY be appended; the archive CLI preserves them in archived filenames.

## Active Window vs. Archive 🗂️

[CHANGELOG.md](../../../CHANGELOG.md) at the repository root holds the most recent releases inline.
Older releases live one-file-per-version under [docs/changelog/](../../changelog/), linked from the `## Older Releases` section at the bottom of the active changelog.

The active window has a default retention of 7 entries.
A higher count is fine for short bursts of releases, but the active changelog SHOULD stay short enough that scrolling it is cheap.

## Cutting a Release ✂️

1. Update [CHANGELOG.md](../../../CHANGELOG.md): prepend a new `## [<version>] - <YYYY-MM-DD>` section with the change set, written in the same style as the existing entries.
   When the release ships package metadata, also update [packaging/debian/changelog](../../../packaging/debian/changelog) and the `%changelog` section of [packaging/fedora/infinito-nexus.spec](../../../packaging/fedora/infinito-nexus.spec) with the corresponding entries.
2. Trim [CHANGELOG.md](../../../CHANGELOG.md) and mirror its kept entries into the package changelogs:

   ```bash
   python -m cli.contributing.changelog.archive
   ```

   The CLI keeps the most recent 7 entries (override with `--keep N`) and processes each of the following files:

   - [CHANGELOG.md](../../../CHANGELOG.md) is trimmed; every older entry is written to its own file under [docs/changelog/](../../changelog/) named `<padded-semver>-<release-date>.md`, and the `## Older Releases` index at the bottom of the active changelog is rebuilt from the archive directory listing so it never drifts away from what is on disk.
   - [packaging/debian/changelog](../../../packaging/debian/changelog) and the `%changelog` section of [packaging/fedora/infinito-nexus.spec](../../../packaging/fedora/infinito-nexus.spec) are regenerated from the kept CHANGELOG.md entries, with a trailing notice that points at [docs.infinito.nexus](https://docs.infinito.nexus/) for further releases and a plain-text list of the archived versions and their dates (no links).

   Pass `--dry-run` to preview without writing.
3. Run `make test` locally and confirm everything is green.
4. Commit the changelog and any archive additions in a single commit with subject `Release version <MAJOR>.<MINOR>.<PATCH>` (matching the historical convention).
5. Tag the commit: `git tag -a v<MAJOR>.<MINOR>.<PATCH> -m "Release version <MAJOR>.<MINOR>.<PATCH>"`.
6. Push the branch and the tag with [git-sign-push](https://github.com/kevinveenbirkenbach/git-maintainer-tools), running it outside the sandbox.

## CI on Tag Push 🤖

A `v*` tag push fans out into two CI workflows:

| Workflow | Purpose |
|---|---|
| [release-version.yml](../../../.github/workflows/release-version.yml) | Backfills CI images for the version tag if missing, retags them to release tags, and publishes the version-specific image set. |
| [release-highest.yml](../../../.github/workflows/release-highest.yml) | Decides whether the new version is the highest published version and, if so, advances the `latest` floating tag. |

Both run from the trusted workflow ref and check out the version tag for the actual build payload, so the release artefacts match the tagged commit byte-for-byte.

## Idempotence 🔁

The archive CLI is byte-idempotent.
Re-running it on an already-processed tree leaves every file unchanged: CHANGELOG.md is rewritten only when its target content differs from disk, the per-release archive files are never overwritten, and the package changelogs are only rewritten when the regenerated content differs from disk.
This makes it safe to run from a pre-commit hook, a release script, or by hand without keeping track of state.

## Related Pages 🔗

- [docs/changelog/README.md](../../changelog/README.md) describes the archive directory layout.
- [pipeline.md](../artefact/git/pipeline.md) covers the broader CI orchestrator that hands off to the release workflows.
