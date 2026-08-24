"""Shared test helpers for ``cli.contributing.changelog.archive``."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory


def make_changelog_md(versions: list[tuple[str, str, str]]) -> str:
    """Build a synthetic ``CHANGELOG.md`` body. *versions* is a list
    of ``(version, date, bullet)`` triples; each becomes one
    ``## [version] - date`` section with a single bullet line.
    """
    sections = [f"## [{v}] - {d}\n* {bullet}\n" for v, d, bullet in versions]
    return "\n".join(sections)


def kept_for_mirror(
    versions: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Build the ``(version, date, body_md)`` tuples the mirror
    functions expect: the body is the markdown after the
    ``## [version]`` header.
    """
    return [(v, d, f"* {bullet}\n") for v, d, bullet in versions]


class TempRepoMixin:
    """Mixin that gives a :class:`unittest.TestCase` a temporary
    repo-shaped directory at ``self.repo_root``, plus the canonical
    ``self.archive_dir`` and ``self.changelog`` paths.

    Mix with :class:`unittest.TestCase`. The mixin chains
    ``super().setUp()`` so cooperative initialisation keeps working.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_root = Path(self._tmp.name)
        self.archive_dir = self.repo_root / "docs" / "changelog"
        self.changelog = self.repo_root / "CHANGELOG.md"
        super().setUp()
