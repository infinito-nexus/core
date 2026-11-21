"""Self-expiring removal guards: no project file names a removed name again.

One walk reads every project file outside ``locale/`` once; each guard keeps its
own names, exclusions and sunset, and from its sunset fails with a reminder to
delete it. ``locale/`` is skipped, because the i18n extraction regenerates it
from the documentation. A branch from before a removal still sets or reads the
old name, which Ansible accepts in silence or resolves only when its task runs;
each guard fails on it instead.

``TorEgressRouterEnabled`` (sunset 2027-02-06)
    ``services.tor.egress.route`` (``none``, ``onion``, ``all``) replaced the
    boolean ``services.tor.egress.enabled``, and ``TOR_EGRESS_ROUTE`` replaced the
    variable that read it. The requirement documents, which record the
    migration under the old names, are skipped.

``ModeNames`` (sunset 2027-02-04)
    The modes of ``group_vars/all/01_modes.yml`` dropped their ``MODE_`` prefix,
    ``MODE_ASSERT`` became ``VALIDATE`` (CLI flag ``--validate``) and
    ``MODE_ASSERT_LOCAL`` is gone. The entries of released versions in
    ``CHANGELOG.md``, ``packaging/debian/changelog`` and
    ``packaging/fedora/infinito-nexus.spec`` are history and skipped. A version
    counts as released once its ``CHANGELOG.md`` section header carries a date;
    a Debian entry also needs a distribution other than ``UNRELEASED``.

``ContainerHardRepair`` (sunset 2027-02-05)
    ``sys-ctl-rpr-container-hard`` ran ``compose down`` and ``up -d`` on every
    instance below ``DIR_COMPOSITIONS`` each Sunday, so every application went
    down once a week and running CI jobs died with it.
    ``sys-ctl-rpr-container-soft`` restarts a project once one of its containers
    is unhealthy or exited, so the role, its units and its service, schedule and
    timeout variables are gone. A leftover ``roles/`` directory puts its unit
    back into ``SYS_SERVICE_GROUP_REPAIR``. The retirement in
    ``sys-svc-compose`` keeps the role id on its one
    ``COMPOSE_RETIRED_SERVICE_ID`` line, its test spells the unit names out, and
    the release notes list the removed role under "Removed".

``AsyncEnabled`` (sunset 2027-02-03)
    Every task that read the switch now runs async with ``ASYNC_TIME`` and
    ``ASYNC_POLL``, and the full-cycle deploy marks its second pass with
    ``DEPLOY_IS_UPDATE``.

``DocsAgents`` (sunset 2027-02-18, criterion L26)
    The removed agent-docs tree stays gone and no live file points into it; it
    also reads the files ``.gitignore`` excludes, and skips ``docs/changelog/``
    and ``docs/requirements/``. ``tests/lint/agents/test_l26_docs_agents_removed.py``
    proves the rest of L26.
"""

from __future__ import annotations

import datetime as dt
import re
import unittest
from functools import cache
from pathlib import Path
from typing import ClassVar

from utils.cache.files import iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT, files_outside_locale

_LOCALE = "locale/"
_SELF_REL = Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix()


@cache
def _project_files() -> tuple[tuple[str, str, bool], ...]:
    """Every readable project file outside ``locale/`` but this module, read once.

    Returns:
        ``(path relative to the project root, content, git would track it)``.
    """
    tracked = {path for _, path in files_outside_locale()}
    files: list[tuple[str, str, bool]] = []
    for path in iter_project_files():
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith(_LOCALE) or rel == _SELF_REL:
            continue
        try:
            files.append((rel, read_text(path), path in tracked))
        except (OSError, UnicodeDecodeError):
            continue
    return tuple(files)


@cache
def _tracked_files() -> tuple[tuple[str, str], ...]:
    return tuple((rel, text) for rel, text, tracked in _project_files() if tracked)


def _numbered(text: str, pattern: re.Pattern[str]) -> list[int]:
    if not pattern.search(text):
        return []
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if pattern.search(line)
    ]


class TorEgressRouterEnabled:
    NAME = "TOR_EGRESS_ROUTER_ENABLED"
    SUNSET = dt.date(2027, 2, 6)
    SKIPPED_PREFIXES = (_LOCALE, "docs/requirements/")
    _NAME_RE = re.compile(rf"\b{NAME}\b")

    @classmethod
    def expired(cls, today: dt.date) -> bool:
        return today >= cls.SUNSET

    @classmethod
    def skipped(cls, rel: str) -> bool:
        """Whether the guard leaves the file at *rel* unread.

        Args:
            rel: the file's path relative to the project root.
        """
        return rel.startswith(cls.SKIPPED_PREFIXES)

    @classmethod
    def named_lines(cls, text: str) -> list[int]:
        """Line numbers of *text* that name the removed variable.

        Args:
            text: the content of one project file.
        """
        return _numbered(text, cls._NAME_RE)


class ModeNames:
    RENAMES: ClassVar[dict[str, str]] = {
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
    CHANGELOG_MD = "CHANGELOG.md"
    DEBIAN_CHANGELOG = "packaging/debian/changelog"
    FEDORA_SPEC = "packaging/fedora/infinito-nexus.spec"
    _NAME_RE = re.compile(
        rf"\b(?:{'|'.join(sorted(RENAMES, key=len, reverse=True))})\b"
    )
    _MD_RELEASE_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}\s*$")
    _DEB_ENTRY_RE = re.compile(r"^\S+ \((\d+\.\d+\.\d+)-[^)]*\) (\S+);")
    _RPM_ENTRY_RE = re.compile(r"^\* .+ - (\d+\.\d+\.\d+)-\S+\s*$")

    @classmethod
    def expired(cls, today: dt.date) -> bool:
        return today >= cls.SUNSET

    @classmethod
    def released_versions(cls, changelog: str) -> frozenset[str]:
        """
        Args:
            changelog: the content of ``CHANGELOG.md``.

        Returns:
            Every version whose section header carries a release date.
        """
        return frozenset(
            match.group(1)
            for line in changelog.splitlines()
            if (match := cls._MD_RELEASE_RE.match(line))
        )

    @classmethod
    def _markdown_entries(cls, lines: list[str], released: frozenset[str]):
        current = False
        for number, line in enumerate(lines, start=1):
            if line.startswith("## "):
                match = cls._MD_RELEASE_RE.match(line)
                current = match is not None and match.group(1) in released
            yield number, current

    @classmethod
    def _debian_entries(cls, lines: list[str], released: frozenset[str]):
        current = False
        for number, line in enumerate(lines, start=1):
            if match := cls._DEB_ENTRY_RE.match(line):
                current = match.group(1) in released and match.group(2) != "UNRELEASED"
            yield number, current

    @classmethod
    def _rpm_entries(cls, lines: list[str], released: frozenset[str]):
        in_changelog = current = False
        for number, line in enumerate(lines, start=1):
            if line.startswith("%"):
                in_changelog, current = line.strip() == "%changelog", False
            elif in_changelog and (match := cls._RPM_ENTRY_RE.match(line)):
                current = match.group(1) in released
            yield number, current

    @classmethod
    def released_lines(
        cls, rel: str, text: str, released: frozenset[str]
    ) -> frozenset[int]:
        """
        Args:
            rel: the file's path relative to the project root.
            text: its content.
            released: the versions ``released_versions`` returned.

        Returns:
            The line numbers inside a changelog entry of a released version, none
            for a file that is no changelog.
        """
        entries = {
            cls.CHANGELOG_MD: cls._markdown_entries,
            cls.DEBIAN_CHANGELOG: cls._debian_entries,
            cls.FEDORA_SPEC: cls._rpm_entries,
        }.get(rel)
        if entries is None:
            return frozenset()
        return frozenset(
            number for number, inside in entries(text.splitlines(), released) if inside
        )

    @classmethod
    def named(cls, text: str) -> list[tuple[int, str]]:
        """Line numbers and old names that *text* still carries.

        Args:
            text: the content of one project file.
        """
        if not cls._NAME_RE.search(text):
            return []
        return [
            (number, match.group(0))
            for number, line in enumerate(text.splitlines(), start=1)
            for match in cls._NAME_RE.finditer(line)
        ]

    @classmethod
    def old_names(cls, files: list[tuple[str, str]]) -> list[str]:
        """
        Args:
            files: ``(relative path, content)`` of every scanned file.

        Returns:
            One ``path:line: OLD -> NEW`` per old name outside a changelog entry
            of a released version.
        """
        released = cls.released_versions(dict(files).get(cls.CHANGELOG_MD, ""))
        found = []
        for rel, content in files:
            exempt = cls.released_lines(rel, content, released)
            found.extend(
                f"{rel}:{line}: {old} -> {cls.RENAMES[old]}"
                for line, old in cls.named(content)
                if line not in exempt
            )
        return found


class ContainerHardRepair:
    ROLE = "sys-ctl-rpr-container-hard"
    NAMES = (
        "rpr-container-hard",
        "rpr_container_hard",
        "SYS_SERVICE_REPAIR_CONTAINER_HARD",
        "SYS_SCHEDULE_REPAIR_DOCKER_HARD",
        "SYS_TIMEOUT_CONTAINER_RPR_HARD",
    )
    SUNSET = dt.date(2027, 2, 5)
    RELEASE_NOTES = frozenset(
        {
            "CHANGELOG.md",
            "packaging/debian/changelog",
            "packaging/fedora/infinito-nexus.spec",
        }
    )
    RETIREMENT_VARS = f"roles/sys-svc-compose/{ROLE_FILE_VARS_MAIN}"
    RETIREMENT_KEY = "COMPOSE_RETIRED_SERVICE_ID:"
    RETIREMENT_TEST = "tests/unit/python/roles/sys-svc-compose/test_retire.py"
    _NAME_RE = re.compile("|".join(re.escape(name) for name in NAMES))

    @classmethod
    def expired(cls, today: dt.date) -> bool:
        return today >= cls.SUNSET

    @classmethod
    def skipped(cls, rel: str) -> bool:
        """Whether the guard leaves the file at *rel* unread.

        Args:
            rel: the file's path relative to the project root.
        """
        return (
            rel.startswith(_LOCALE)
            or rel in cls.RELEASE_NOTES
            or rel == cls.RETIREMENT_TEST
        )

    @classmethod
    def named(cls, rel: str, text: str) -> list[tuple[int, str]]:
        """Line numbers and removed names that *text* carries outside the retirement.

        Args:
            rel: the file's path relative to the project root.
            text: the file's content.
        """
        if not cls._NAME_RE.search(text):
            return []
        return [
            (number, match.group(0))
            for number, line in enumerate(text.splitlines(), start=1)
            if not (rel == cls.RETIREMENT_VARS and line.startswith(cls.RETIREMENT_KEY))
            for match in cls._NAME_RE.finditer(line)
        ]

    @classmethod
    def findings(cls, rel: str, text: str) -> list[tuple[int, str]]:
        """Line numbers and removed names the guard reports for the file at *rel*.

        Args:
            rel: the file's path relative to the project root.
            text: the file's content.
        """
        return [] if cls.skipped(rel) else cls.named(rel, text)


class AsyncEnabled:
    NAME = "ASYNC_ENABLED"
    SUNSET = dt.date(2027, 2, 3)
    _NAME_RE = re.compile(rf"\b{NAME}\b")

    @classmethod
    def expired(cls, today: dt.date) -> bool:
        return today >= cls.SUNSET

    @classmethod
    def named_lines(cls, text: str) -> list[int]:
        """Line numbers of *text* that name the removed switch.

        Args:
            text: the content of one project file.
        """
        return _numbered(text, cls._NAME_RE)


class DocsAgents:
    NEEDLE = "docs/" + "agents"
    SUNSET = dt.date(2027, 2, 18)
    EXEMPT_PREFIXES = ("docs/changelog/", "docs/requirements/", _LOCALE)

    @classmethod
    def expired(cls, today: dt.date) -> bool:
        return today >= cls.SUNSET

    @classmethod
    def reference_problems(cls, items) -> list[str]:
        """Return a problem per (relpath, content) pair that names the removed tree.

        Args:
            items: iterable of ``(repo-relative posix path, file content)``.
        """
        return [
            f"{rel}: references the removed {cls.NEEDLE} tree"
            for rel, content in items
            if not rel.startswith(cls.EXEMPT_PREFIXES) and cls.NEEDLE in content
        ]


class TestRemovedNames(unittest.TestCase):
    def _fail_when_expired(self, guard: type, gone: str, extra: str = "") -> None:
        if guard.expired(dt.datetime.now(tz=dt.UTC).date()):
            self.fail(
                f"Removal guard expired (>= {guard.SUNSET.isoformat()}): {gone} is "
                f"long gone. DELETE {guard.__name__}, its test method and its "
                f"negative controls{extra}."
            )

    def test_no_file_names_tor_egress_router_enabled(self) -> None:
        guard = TorEgressRouterEnabled
        self._fail_when_expired(guard, guard.NAME)
        findings = [
            f"{rel}:{line}"
            for rel, content in _tracked_files()
            if not guard.skipped(rel)
            for line in guard.named_lines(content)
        ]
        self.assertEqual(
            findings,
            [],
            f"{guard.NAME} was removed: read the route from TOR_EGRESS_ROUTE "
            "(services.tor.egress.route: none, onion or all) instead:\n"
            + "\n".join(findings),
        )

    def test_no_file_names_an_old_mode(self) -> None:
        self._fail_when_expired(ModeNames, "the MODE_ names")
        findings = ModeNames.old_names(list(_tracked_files()))
        self.assertEqual(
            findings,
            [],
            "The modes lost their MODE_ prefix: DUMMY, DEBUG, RESET, CLEANUP, "
            "VALIDATE (was MODE_ASSERT; CLI --validate), BACKUP, DEMO. Roles read "
            "DEBUG / VALIDATE through lookup('debug') / lookup('validate'):\n"
            + "\n".join(findings),
        )

    def test_the_container_hard_repair_role_directory_is_gone(self) -> None:
        guard = ContainerHardRepair
        self._fail_when_expired(
            guard,
            guard.ROLE,
            ", and the retirement in roles/sys-svc-compose (tasks/retire.yml, its "
            "include in tasks/00_core.yml, the COMPOSE_RETIRED_* vars and "
            f"{guard.RETIREMENT_TEST})",
        )
        self.assertFalse(
            (PROJECT_ROOT / "roles" / guard.ROLE).exists(),
            f"roles/{guard.ROLE} exists, so get_category_entries puts its unit back "
            "into SYS_SERVICE_GROUP_REPAIR and every lock list",
        )

    def test_no_file_names_the_container_hard_repair(self) -> None:
        guard = ContainerHardRepair
        self._fail_when_expired(guard, guard.ROLE)
        found = [
            f"{rel}:{line}: {name}"
            for rel, content in _tracked_files()
            for line, name in guard.findings(rel, content)
        ]
        self.assertEqual(
            found,
            [],
            f"{guard.ROLE} was removed: its weekly compose down and up took every "
            "application down, and sys-ctl-rpr-container-soft restarts a "
            "project with an unhealthy or exited container instead:\n"
            + "\n".join(found),
        )

    def test_no_file_names_async_enabled(self) -> None:
        guard = AsyncEnabled
        self._fail_when_expired(guard, guard.NAME)
        findings = [
            f"{rel}:{line}"
            for rel, content in _tracked_files()
            for line in guard.named_lines(content)
        ]
        self.assertEqual(
            findings,
            [],
            f"{guard.NAME} was removed: tasks run async unconditionally, a task that "
            "must run synchronously drops its async and poll (a sys-service caller "
            "sets system_service_force_linear_sync), and the full-cycle update pass "
            "is DEPLOY_IS_UPDATE:\n" + "\n".join(findings),
        )

    def test_no_live_file_references_the_removed_agent_docs_tree(self) -> None:
        self._fail_when_expired(DocsAgents, DocsAgents.NEEDLE)
        self.assertEqual(
            DocsAgents.reference_problems(
                (rel, content) for rel, content, _ in _project_files()
            ),
            [],
        )


class TestTorEgressRouterEnabledControls(unittest.TestCase):
    def test_a_line_naming_the_removed_variable_is_reported(self) -> None:
        name = TorEgressRouterEnabled.NAME
        text = "\n".join(
            ("TOR_EGRESS_ROUTE: onion", f"when: {name} | bool", f"X{name}")
        )
        self.assertEqual(TorEgressRouterEnabled.named_lines(text), [2])

    def test_the_requirement_history_and_the_catalogs_are_skipped(self) -> None:
        skipped = TorEgressRouterEnabled.skipped
        self.assertTrue(skipped("docs/requirements/history.md"))
        self.assertTrue(skipped("locale/de/LC_MESSAGES/docs.po"))
        self.assertFalse(skipped(f"roles/svc-net-tor/{ROLE_FILE_VARS_MAIN}"))

    def test_expiry_fires_on_the_sunset_date(self) -> None:
        sunset = TorEgressRouterEnabled.SUNSET
        self.assertFalse(TorEgressRouterEnabled.expired(sunset - dt.timedelta(days=1)))
        self.assertTrue(TorEgressRouterEnabled.expired(sunset))


_ROLE_TASKS = f"roles/r/{ROLE_FILE_TASKS_MAIN}"
_RELEASED = {
    ModeNames.CHANGELOG_MD: "## [1.0.0] - 2026-01-01\n- seeded only with MODE_DEMO\n",
    ModeNames.DEBIAN_CHANGELOG: (
        "pkg (1.0.0-1) unstable; urgency=medium\n\n"
        "  - seeded only with MODE_DEMO\n\n"
        " -- A <a@example.org>  Thu, 01 Jan 2026 00:00:00 +0000\n"
    ),
    ModeNames.FEDORA_SPEC: (
        "%changelog\n"
        "* Thu Jan 01 2026 A <a@example.org> - 1.0.0-1\n"
        "- seeded only with MODE_DEMO\n"
    ),
}
_UNRELEASED = {
    ModeNames.CHANGELOG_MD: "## [Unreleased]\n- MODE_DEMO came back\n\n"
    + _RELEASED[ModeNames.CHANGELOG_MD],
    ModeNames.DEBIAN_CHANGELOG: (
        "pkg (1.1.0-1) UNRELEASED; urgency=medium\n\n  - MODE_DEMO came back\n\n"
        " -- A <a@example.org>  Thu, 01 Jan 2026 00:00:00 +0000\n\n"
        "pkg (1.0.1-1) unstable; urgency=medium\n\n  - MODE_DEMO came back\n\n"
        " -- A <a@example.org>  Thu, 01 Jan 2026 00:00:00 +0000\n\n"
        + _RELEASED[ModeNames.DEBIAN_CHANGELOG]
    ),
    ModeNames.FEDORA_SPEC: (
        "Summary: MODE_DEMO\n%changelog\n"
        "* Thu Jan 01 2026 A <a@example.org> - 1.1.0-1\n- MODE_DEMO came back\n\n"
        + _RELEASED[ModeNames.FEDORA_SPEC].removeprefix("%changelog\n")
    ),
    _ROLE_TASKS: "- ansible.builtin.debug:\n    msg: '{{ MODE_DEMO }}'\n",
}


class TestReleasedChangelogEntries(unittest.TestCase):
    def test_an_entry_of_a_released_version_keeps_its_old_name(self) -> None:
        self.assertEqual(ModeNames.old_names(list(_RELEASED.items())), [])

    def test_an_unreleased_entry_or_code_still_names_the_old_mode(self) -> None:
        self.assertEqual(
            ModeNames.old_names(list(_UNRELEASED.items())),
            [
                f"{ModeNames.CHANGELOG_MD}:2: MODE_DEMO -> DEMO",
                f"{ModeNames.DEBIAN_CHANGELOG}:3: MODE_DEMO -> DEMO",
                f"{ModeNames.DEBIAN_CHANGELOG}:9: MODE_DEMO -> DEMO",
                f"{ModeNames.FEDORA_SPEC}:1: MODE_DEMO -> DEMO",
                f"{ModeNames.FEDORA_SPEC}:4: MODE_DEMO -> DEMO",
                f"{_ROLE_TASKS}:2: MODE_DEMO -> DEMO",
            ],
        )


if __name__ == "__main__":
    unittest.main()
