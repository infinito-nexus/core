"""Lint completeness of the generated package changelogs.

``packaging/debian/changelog`` and the ``%changelog`` section of
``packaging/fedora/infinito-nexus.spec`` are mirrored from the
CHANGELOG.md single-point-of-truth (the inline entries plus every
archived release under ``docs/changelog/``). These checks fail when a
released version is missing from either package changelog, so a stale or
mis-generated mirror is caught before it ships.

See [release.md](../../../../docs/contributing/actions/release.md).
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

_CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"
_ARCHIVE_DIR = PROJECT_ROOT / "docs" / "changelog"
_DEBIAN = PROJECT_ROOT / "packaging" / "debian" / "changelog"
_FEDORA = PROJECT_ROOT / "packaging" / "fedora" / "infinito-nexus.spec"

_CHANGELOG_HEADER = re.compile(r"^## \[([^\]]+)\] - ", re.MULTILINE)
_ARCHIVE_NAME = re.compile(r"^(\d+)\.(\d+)\.(\d+)-")
_DEBIAN_STANZA = re.compile(r"^infinito-nexus \(([^)]+?)-1\) ", re.MULTILINE)
_RPM_STANZA = re.compile(r"^\* .+ - ([0-9][^ ]*?)-1\s*$", re.MULTILINE)
_FOOTER_VERSION = re.compile(r"(\d+\.\d+\.\d+) \(\d{4}-\d\d-\d\d\)")


def _changelog_inline_versions() -> set[str]:
    return set(_CHANGELOG_HEADER.findall(read_text(str(_CHANGELOG))))


def _archived_versions() -> set[str]:
    versions: set[str] = set()
    for path in _ARCHIVE_DIR.glob("*.md"):
        match = _ARCHIVE_NAME.match(path.name)
        if match:
            versions.add(".".join(str(int(part)) for part in match.groups()))
    return versions


def _debian_inline_versions() -> set[str]:
    return set(_DEBIAN_STANZA.findall(read_text(str(_DEBIAN))))


def _debian_versions() -> set[str]:
    text = read_text(str(_DEBIAN))
    return set(_DEBIAN_STANZA.findall(text)) | set(_FOOTER_VERSION.findall(text))


def _fedora_changelog_section() -> str:
    text = read_text(str(_FEDORA))
    return text[text.index("%changelog") :]


def _fedora_inline_versions() -> set[str]:
    return set(_RPM_STANZA.findall(_fedora_changelog_section()))


def _fedora_versions() -> set[str]:
    section = _fedora_changelog_section()
    return set(_RPM_STANZA.findall(section)) | set(_FOOTER_VERSION.findall(section))


class TestPackageChangelogCompleteness(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.changelog_inline = _changelog_inline_versions()
        cls.expected = cls.changelog_inline | _archived_versions()

    def _assert_complete(self, target: str, actual: set[str]) -> None:
        missing = sorted(self.expected - actual, key=_sort_key)
        extra = sorted(actual - self.expected, key=_sort_key)
        problems = []
        if missing:
            problems.append(f"missing from {target}: {missing}")
        if extra:
            problems.append(f"unknown versions in {target}: {extra}")
        if problems:
            self.fail(
                f"{target} is out of sync with the CHANGELOG.md SPOT "
                f"(inline entries + docs/changelog/). Regenerate with "
                f"`python -m cli.contributing.changelog.archive`.\n"
                + "\n".join(problems)
            )

    def test_debian_changelog_lists_every_release(self) -> None:
        self._assert_complete("packaging/debian/changelog", _debian_versions())

    def test_fedora_spec_lists_every_release(self) -> None:
        self._assert_complete(
            "packaging/fedora/infinito-nexus.spec", _fedora_versions()
        )

    def test_inline_window_matches_changelog(self) -> None:
        for target, inline in (
            ("packaging/debian/changelog", _debian_inline_versions()),
            ("packaging/fedora/infinito-nexus.spec", _fedora_inline_versions()),
        ):
            with self.subTest(target=target):
                self.assertEqual(
                    inline,
                    self.changelog_inline,
                    f"{target} inline stanzas drifted from the CHANGELOG.md "
                    f"window; regenerate with "
                    f"`python -m cli.contributing.changelog.archive`.",
                )


def _sort_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
