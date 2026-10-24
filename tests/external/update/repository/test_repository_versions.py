"""Warn about outdated git `ref:` values in `roles/*/meta/services.yml`
and `roles/*/meta/addons/*.yml`.

For every entity (at any depth — top-level entity, sub-entity, plugin
map, addon ``config``) that declares BOTH `repository:` and `ref:`, this
test warns when the upstream moved on: a semver-compatible ref is
checked against the repository's git tags
(``git ls-remote --tags <repository>``), a full 40-hex commit SHA
against the tip of its default branch
(``git ls-remote <repository> HEAD``).

Counterpart to ``tests/external/update/docker/test_image_versions.py``
(that one bumps OCI image tags, this one bumps git refs for
from-source builds, plugin and build-helper repos).
The shared discovery / version logic lives in
:mod:`utils.update.repository`; the CI auto-update job at
``.github/workflows/cron-update.yml`` (``update-repository-refs``) consumes
the same module to open PRs against ``main``.

External test: depends on live ``git ls-remote`` calls against the
remotes declared in services.yml. The test always passes so normal
validation stays stable even when remotes are slow or unreachable;
outdated refs surface as warnings on stdout and as GitHub Actions
``::warning::`` annotations on the offending services.yml line.

Suppress a check by placing ``# nocheck: repository-version`` on the
line directly above the ``ref:`` key (blank lines between are
ignored). Branch refs (``master``, ``main``, ``stable``) and short
SHAs are skipped automatically; only refs that match
:func:`utils.update.base.is_semver` or
:func:`utils.update.repository.is_commit_sha` are checked.
"""

from __future__ import annotations

import unittest

from utils.annotations.message import warning
from utils.update.repository import (
    collect_entries,
    find_outdated_updates,
)

from . import PROJECT_ROOT


class TestRepositoryVersions(unittest.TestCase):
    """Warn about outdated semver and commit-SHA `ref:` values."""

    def test_repository_refs_are_current(self) -> None:
        entries = collect_entries(PROJECT_ROOT)
        updates = find_outdated_updates(PROJECT_ROOT)

        if updates:
            col_w = (28, 30, 50, 12)
            header = (
                f"{'Role':<{col_w[0]}} {'Entity':<{col_w[1]}} "
                f"{'Repository':<{col_w[2]}} {'Current':<{col_w[3]}} Latest"
            )
            rows = "\n".join(
                f"{u.entry.role:<{col_w[0]}} "
                f"{'.'.join(u.entry.entity_path) or '<root>':<{col_w[1]}} "
                f"{u.entry.repository:<{col_w[2]}} "
                f"{u.entry.ref:<{col_w[3]}} {u.latest}"
                for u in updates
            )
            print(
                f"\n⚠️  Outdated repository refs:\n{header}\n{'-' * 140}\n{rows}\n"
                f"\n💡 To suppress a warning add above the ref: key:\n"
                f"  # nocheck: repository-version"
            )
            for u in updates:
                entity = ".".join(u.entry.entity_path) or "<root>"
                msg = (
                    f"{u.entry.role}/{entity}: {u.entry.repository} is at "
                    f"{u.entry.ref}, upstream is at {u.latest}"
                )
                warning(
                    msg,
                    title="Outdated repository ref",
                    file=str(u.entry.config_path.relative_to(PROJECT_ROOT)),
                    line=u.entry.line,
                )

        self.assertIsNotNone(entries)


if __name__ == "__main__":
    unittest.main()
