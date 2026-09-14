"""Check exact pip pins in ``roles/**/*.yml`` against PyPI.

A pin freezes a version and nothing thaws it: the docker updater tracks image
tags, dependabot reads ``pyproject.toml``, and neither sees a version inside an
Ansible task variable. This reports the gap as GitHub Actions ``::warning::``
annotations.

Like the Docker check this is an opt-in external test that always passes, so
normal validation stays stable when PyPI is slow, and it never blocks on a
release the repository has deliberately not taken yet.

Suppress a package by placing ``# nocheck: pip-version`` on the line directly
above the ``package_name:`` key, or on the key itself.
"""

from __future__ import annotations

import unittest

from utils.annotations.message import warning
from utils.update.pip import collect_entries, find_outdated_updates

from . import PROJECT_ROOT

_REPO_ROOT = PROJECT_ROOT


class TestPipPins(unittest.TestCase):
    """Warn about pinned pip requirements that PyPI has moved past."""

    def test_pinned_requirements_are_current(self) -> None:
        entries = collect_entries(_REPO_ROOT)
        self.assertTrue(entries, "No exact pip pins found under roles/")

        updates = find_outdated_updates(_REPO_ROOT)
        if not updates:
            return

        col_w = (32, 32, 18)
        header = (
            f"{'Role':<{col_w[0]}} {'Package':<{col_w[1]}} "
            f"{'Current':<{col_w[2]}} Latest"
        )
        rows = "\n".join(
            f"{u.entry.role:<{col_w[0]}} {u.entry.package:<{col_w[1]}} "
            f"{u.entry.version:<{col_w[2]}} {u.latest}"
            for u in updates
        )
        print(
            f"\n⚠️  Outdated pip pins:\n{header}\n{'-' * 100}\n{rows}\n\n"
            "💡 To suppress a warning add above the package_name: key:\n"
            "  # nocheck: pip-version"
        )
        for update in updates:
            warning(
                f"{update.entry.role}: {update.entry.package} is pinned at "
                f"{update.entry.version}, latest on PyPI is {update.latest}",
                title="Outdated pip pin",
                file=str(update.entry.config_path.relative_to(_REPO_ROOT)),
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
