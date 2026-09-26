"""Warn about pins whose declared upstream has moved ahead.

A pin outside the Docker and repository updaters names its upstream in an
``update:`` block of ``roles/*/meta/services.yml``. This test resolves each
declared source and warns when it offers a newer version.

Counterpart to ``tests/external/update/docker/test_image_versions.py`` and
``tests/external/update/repository/test_repository_versions.py``. The shared
logic lives in :mod:`utils.update.source`; the CI auto-update job at
``.github/workflows/cron-update.yml`` (``update-version-sources``) consumes the
same module to open PRs against ``main``.

External test: depends on live registry, npm, git and HTTP calls. It always
passes, so normal validation stays stable when an upstream is slow or
unreachable; outdated pins surface as warnings and as GitHub Actions
annotations on the offending line.

Suppress a check with ``# nocheck: version-source`` on the line above the pin.
"""

from __future__ import annotations

import unittest

from utils.annotations.message import warning
from utils.update.source import collect_entries, find_outdated_updates

from . import PROJECT_ROOT


class TestVersionSources(unittest.TestCase):
    """Warn about outdated pins that declare their own upstream source."""

    def test_declared_version_sources_are_current(self) -> None:
        entries = collect_entries(PROJECT_ROOT)
        updates = find_outdated_updates(PROJECT_ROOT)

        if updates:
            rows = "\n".join(
                f"{u.entry.role}/{u.entry.entity}.{u.entry.key}: "
                f"{u.entry.current} -> {u.latest} ({u.entry.source.get('type')})"
                for u in updates
            )
            print(
                f"\n⚠️  Outdated version pins:\n{rows}\n"
                "\n💡 To suppress a warning add above the pinned key:\n"
                "  # nocheck: version-source"
            )
            for u in updates:
                warning(
                    f"{u.entry.role}/{u.entry.entity}.{u.entry.key} is at "
                    f"{u.entry.current}, its source offers {u.latest}",
                    title="Outdated version pin",
                    file=str(u.entry.config_path.relative_to(PROJECT_ROOT)),
                    line=u.entry.line,
                )

        self.assertIsNotNone(entries)


if __name__ == "__main__":
    unittest.main()
