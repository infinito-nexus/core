# Changelog Archive 📚

Per-release archive files for [CHANGELOG.md](../../CHANGELOG.md).
The active changelog at the repository root keeps the most recent releases inline; once an entry rolls past the configured retention window, it lives here as its own file.

## Audience 👥

Contributors who need the full version history past the active changelog window, and Sphinx readers following the navigation tree.

## Filename Schema 📁

Every archive file is named `<padded-semver>-<release-date>.md`, where each numeric component of the semver is zero-padded to three digits and the date is the `YYYY-MM-DD` value parsed from the original entry's header.
Padded names sort lexicographically in the same order as the underlying versions, so a directory listing is already in chronological order.

## Maintenance 🛠️

Archive files are produced and the index in [CHANGELOG.md](../../CHANGELOG.md) is rebuilt by [the changelog archive CLI](../contributing/actions/release.md).
Do NOT edit archive files by hand: the source of truth for new entries is [CHANGELOG.md](../../CHANGELOG.md), and the CLI moves an entry here exactly once when it leaves the active window.
