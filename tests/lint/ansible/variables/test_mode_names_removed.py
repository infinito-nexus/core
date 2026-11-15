"""Self-expiring removal guard: no project file names a ``MODE_``-prefixed mode.

The modes of ``group_vars/all/01_modes.yml`` dropped their prefix, ``MODE_ASSERT``
became ``VALIDATE`` (CLI flag ``--validate``) and ``MODE_ASSERT_LOCAL`` is gone.
A branch from before the rename still sets or reads an old name, which Ansible
accepts in silence as an unrelated variable; this guard fails on it instead.
``locale/`` is skipped, because the i18n extraction regenerates it from the
documentation, and so are the entries of released versions in ``CHANGELOG.md``,
``packaging/debian/changelog`` and ``packaging/fedora/infinito-nexus.spec``,
because a release's notes are history. A version counts as released once its
``CHANGELOG.md`` section header carries a date; a Debian entry also needs a
distribution other than ``UNRELEASED``.

SELF-EXPIRING: from 2027-02-04 it fails with a reminder to delete it.
"""

from __future__ import annotations

import datetime as dt
import re
import unittest
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from . import PROJECT_ROOT

RENAMES: dict[str, str] = {
    "MODE_DUMMY": "DUMMY",
    "MODE_DEBUG": "DEBUG",
    "MODE_RESET": "RESET",
    "MODE_CLEANUP": "CLEANUP",
    "MODE_ASSERT": "VALIDATE",
    "MODE_ASSERT_LOCAL": "VALIDATE",
    "MODE_BACKUP": "BACKUP",
    "MODE_DEMO": "DEMO",
}
SUNSET = dt.date(2027, 2, 4)
SKIPPED_PREFIX = "locale/"
CHANGELOG_MD = "CHANGELOG.md"
DEBIAN_CHANGELOG = "packaging/debian/changelog"
FEDORA_SPEC = "packaging/fedora/infinito-nexus.spec"
ROLE_TASKS = f"roles/r/{ROLE_FILE_TASKS_MAIN}"
_NAME_RE = re.compile(rf"\b(?:{'|'.join(sorted(RENAMES, key=len, reverse=True))})\b")
_SELF = Path(__file__).resolve()
_MD_RELEASE_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}\s*$")
_DEB_ENTRY_RE = re.compile(r"^\S+ \((\d+\.\d+\.\d+)-[^)]*\) (\S+);")
_RPM_ENTRY_RE = re.compile(r"^\* .+ - (\d+\.\d+\.\d+)-\S+\s*$")


def released_versions(changelog: str) -> frozenset[str]:
    """
    Args:
        changelog: the content of ``CHANGELOG.md``.

    Returns:
        Every version whose section header carries a release date.
    """
    return frozenset(
        match.group(1)
        for line in changelog.splitlines()
        if (match := _MD_RELEASE_RE.match(line))
    )


def _markdown_entries(lines: list[str], released: frozenset[str]):
    current = False
    for number, line in enumerate(lines, start=1):
        if line.startswith("## "):
            match = _MD_RELEASE_RE.match(line)
            current = match is not None and match.group(1) in released
        yield number, current


def _debian_entries(lines: list[str], released: frozenset[str]):
    current = False
    for number, line in enumerate(lines, start=1):
        if match := _DEB_ENTRY_RE.match(line):
            current = match.group(1) in released and match.group(2) != "UNRELEASED"
        yield number, current


def _rpm_entries(lines: list[str], released: frozenset[str]):
    in_changelog = current = False
    for number, line in enumerate(lines, start=1):
        if line.startswith("%"):
            in_changelog, current = line.strip() == "%changelog", False
        elif in_changelog and (match := _RPM_ENTRY_RE.match(line)):
            current = match.group(1) in released
        yield number, current


_ENTRIES = {
    CHANGELOG_MD: _markdown_entries,
    DEBIAN_CHANGELOG: _debian_entries,
    FEDORA_SPEC: _rpm_entries,
}


def released_lines(rel: str, text: str, released: frozenset[str]) -> frozenset[int]:
    """
    Args:
        rel: the file's path relative to the project root.
        text: its content.
        released: the versions ``released_versions`` returned.

    Returns:
        The line numbers inside a changelog entry of a released version, none
        for a file that is no changelog.
    """
    entries = _ENTRIES.get(rel)
    if entries is None:
        return frozenset()
    return frozenset(
        number for number, inside in entries(text.splitlines(), released) if inside
    )


def expired(today: dt.date) -> bool:
    return today >= SUNSET


def _scanned() -> list[tuple[str, str]]:
    files = []
    for path in iter_non_ignored_files():
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith(SKIPPED_PREFIX) or Path(path).resolve() == _SELF:
            continue
        try:
            files.append((rel, read_text(path)))
        except (OSError, UnicodeDecodeError):
            continue
    return files


def named(text: str) -> list[tuple[int, str]]:
    """Line numbers and old names that *text* still carries.

    Args:
        text: the content of one project file.
    """
    return [
        (number, match.group(0))
        for number, line in enumerate(text.splitlines(), start=1)
        for match in _NAME_RE.finditer(line)
    ]


def old_names(files: list[tuple[str, str]]) -> list[str]:
    """
    Args:
        files: ``(relative path, content)`` of every scanned file.

    Returns:
        One ``path:line: OLD -> NEW`` per old name outside a changelog entry
        of a released version.
    """
    released = released_versions(dict(files).get(CHANGELOG_MD, ""))
    found = []
    for rel, content in files:
        exempt = released_lines(rel, content, released)
        found.extend(
            f"{rel}:{line}: {old} -> {RENAMES[old]}"
            for line, old in named(content)
            if line not in exempt
        )
    return found


RELEASED = {
    CHANGELOG_MD: "## [1.0.0] - 2026-01-01\n- seeded only with MODE_DEMO\n",
    DEBIAN_CHANGELOG: (
        "pkg (1.0.0-1) unstable; urgency=medium\n\n"
        "  - seeded only with MODE_DEMO\n\n"
        " -- A <a@example.org>  Thu, 01 Jan 2026 00:00:00 +0000\n"
    ),
    FEDORA_SPEC: (
        "%changelog\n"
        "* Thu Jan 01 2026 A <a@example.org> - 1.0.0-1\n"
        "- seeded only with MODE_DEMO\n"
    ),
}
UNRELEASED = {
    CHANGELOG_MD: "## [Unreleased]\n- MODE_DEMO came back\n\n" + RELEASED[CHANGELOG_MD],
    DEBIAN_CHANGELOG: (
        "pkg (1.1.0-1) UNRELEASED; urgency=medium\n\n  - MODE_DEMO came back\n\n"
        " -- A <a@example.org>  Thu, 01 Jan 2026 00:00:00 +0000\n\n"
        "pkg (1.0.1-1) unstable; urgency=medium\n\n  - MODE_DEMO came back\n\n"
        " -- A <a@example.org>  Thu, 01 Jan 2026 00:00:00 +0000\n\n"
        + RELEASED[DEBIAN_CHANGELOG]
    ),
    FEDORA_SPEC: (
        "Summary: MODE_DEMO\n%changelog\n"
        "* Thu Jan 01 2026 A <a@example.org> - 1.1.0-1\n- MODE_DEMO came back\n\n"
        + RELEASED[FEDORA_SPEC].removeprefix("%changelog\n")
    ),
    ROLE_TASKS: "- ansible.builtin.debug:\n    msg: '{{ MODE_DEMO }}'\n",
}


class TestReleasedChangelogEntries(unittest.TestCase):
    def test_an_entry_of_a_released_version_keeps_its_old_name(self) -> None:
        self.assertEqual(old_names(list(RELEASED.items())), [])

    def test_an_unreleased_entry_or_code_still_names_the_old_mode(self) -> None:
        self.assertEqual(
            old_names(list(UNRELEASED.items())),
            [
                f"{CHANGELOG_MD}:2: MODE_DEMO -> DEMO",
                f"{DEBIAN_CHANGELOG}:3: MODE_DEMO -> DEMO",
                f"{DEBIAN_CHANGELOG}:9: MODE_DEMO -> DEMO",
                f"{FEDORA_SPEC}:1: MODE_DEMO -> DEMO",
                f"{FEDORA_SPEC}:4: MODE_DEMO -> DEMO",
                f"{ROLE_TASKS}:2: MODE_DEMO -> DEMO",
            ],
        )


class TestModeNamesRemoved(unittest.TestCase):
    def test_no_file_names_an_old_mode(self) -> None:
        if expired(dt.datetime.now(tz=dt.UTC).date()):
            self.fail(
                f"Removal guard expired (>= {SUNSET.isoformat()}): the MODE_ names "
                "are long gone. DELETE this guard test file and its negative controls."
            )
        findings = old_names(_scanned())
        self.assertEqual(
            findings,
            [],
            "The modes lost their MODE_ prefix: DUMMY, DEBUG, RESET, CLEANUP, "
            "VALIDATE (was MODE_ASSERT; CLI --validate), BACKUP, DEMO. Roles read "
            "DEBUG / VALIDATE through lookup('debug') / lookup('validate'):\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
