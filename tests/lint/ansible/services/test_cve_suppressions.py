"""Lint: every CVE suppression in a role's ``meta/services.yml`` is justified and dated.

An entry under ``<service>.security.suppressions`` needs ``id: CVE-YYYY-NNNN``
or an ``image_tag`` equal to the service's ``version``, an ``until:
YYYY-MM-DD`` that has not passed and lies no later than ``LATEST_UNTIL``, and a
``# nocheck: cve <reason>`` marker on the line directly above it::

    checkmk:
      image: checkmk/check-mk-raw
      version: "2.4.0p39"
      security:
        suppressions:
          # nocheck: cve the vulnerable module is not loaded by the site
          - id: CVE-2026-1234
            until: 2026-11-30
          # nocheck: cve upstream ships no rebuild with the fixed packages yet
          - image_tag: "2.4.0p39"
            until: 2026-11-30
"""

from __future__ import annotations

import datetime as dt
import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.security.pipeline import pipeline
from utils.security.suppressions import RULE, SuppressionError, parse_entries

from . import PROJECT_ROOT

LATEST_UNTIL = dt.date(2026, 11, 30)
MARKER = re.compile(rf"^\s*#\s*nocheck:\s*{RULE}\b(?P<reason>.*)$", re.IGNORECASE)
BLOCK = re.compile(r"^(?P<indent>\s*)suppressions:\s*$")
ENTRY = re.compile(r"^(?P<indent>\s*)-\s+\S")
REASON_SEPARATORS = " \t-:"


def _entry_lines(lines: list[str]) -> list[int]:
    """Return the index of every list item inside a ``suppressions:`` block."""
    found = []
    block_indent = None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if (
            block_indent is not None
            and indent <= block_indent
            and not line.lstrip().startswith(("-", "#"))
        ):
            block_indent = None
        match = BLOCK.match(line)
        if match:
            block_indent = len(match.group("indent"))
            continue
        if block_indent is not None and ENTRY.match(line):
            found.append(index)
    return found


def _marker_problem(lines: list[str], index: int) -> str | None:
    match = MARKER.match(lines[index - 1]) if index > 0 else None
    if match is None:
        return "has no # nocheck: cve <reason> marker directly above it"
    if not match.group("reason").strip(REASON_SEPARATORS):
        return "its # nocheck: cve marker gives no reason"
    return None


def _until_problems(
    where: str, subject: str, until: dt.date, today: dt.date
) -> list[str]:
    found = []
    if until < today:
        found.append(f"{where}: {subject} expired on {until}")
    if until > LATEST_UNTIL:
        found.append(
            f"{where}: {subject} until {until} lies after the latest allowed day "
            f"{LATEST_UNTIL}"
        )
    return found


def _unmatched_os_problems(
    raw: object, where: str, service: str, today: dt.date
) -> list[str]:
    p = pipeline()
    try:
        releases = p.os_releases(raw)
    except p.ConfigError as exc:
        return [f"{where}: {service} {exc}"]
    return [
        problem
        for release in releases
        for problem in _until_problems(
            where,
            f"{service} unmatched_os {release.name} {release.version}",
            release.until,
            today,
        )
    ]


def problems(text: str, where: str, today: dt.date) -> list[str]:
    """Return every rule one ``meta/services.yml`` breaks.

    Args:
        text: the file content.
        where: the file name for the messages.
        today: the day an ``until`` must not lie before.
    """
    found = []
    lines = text.splitlines()
    for index in _entry_lines(lines):
        problem = _marker_problem(lines, index)
        if problem:
            found.append(f"{where}:{index + 1}: suppression {problem}")
    services = load_yaml_str(text) or {}
    if not isinstance(services, dict):
        return found
    for service, spec in services.items():
        if not isinstance(spec, dict):
            continue
        if "unmatched_os" in spec:
            found += _unmatched_os_problems(spec["unmatched_os"], where, service, today)
        if "security" not in spec:
            continue
        security = spec["security"]
        entries = security.get("suppressions") if isinstance(security, dict) else None
        if not isinstance(entries, list):
            found.append(f"{where}: {service}.security must hold a suppressions list")
            continue
        for entry in entries:
            try:
                parsed = parse_entries([entry], f"{where}: {service}")[0]
            except SuppressionError as exc:
                found.append(str(exc))
                continue
            found += _until_problems(
                where,
                f"{service} suppression of {parsed.subject}",
                parsed.until,
                today,
            )
            version = spec.get("version")
            if parsed.image_tag is not None and parsed.image_tag != str(version):
                found.append(
                    f"{where}: {service} suppression of {parsed.subject} does not "
                    f"match its version {version!r}"
                )
    return found


def unshared_image_tags(services: dict[str, object]) -> list[str]:
    """
    Args:
        services: ``{role: meta/services.yml mapping}`` of every role.

    Returns:
        One message per non-custom service that runs an upstream image tag
        another non-custom service suppresses by ``image_tag`` while it does not.
    """
    running: dict[tuple[str, str], list[str]] = {}
    accepted: dict[tuple[str, str], list[str]] = {}
    for role, declared in sorted(services.items()):
        if not isinstance(declared, dict):
            continue
        for service, spec in declared.items():
            if not isinstance(spec, dict) or spec.get("custom"):
                continue
            if "image" not in spec or "version" not in spec:
                continue
            key = (str(spec["image"]), str(spec["version"]))
            owner = f"{role}:{service}"
            running.setdefault(key, []).append(owner)
            security = spec.get("security")
            entries = (
                security.get("suppressions") if isinstance(security, dict) else None
            )
            if isinstance(entries, list) and any(
                isinstance(entry, dict) and str(entry.get("image_tag")) == key[1]
                for entry in entries
            ):
                accepted.setdefault(key, []).append(owner)
    return [
        f"{owner} runs {image}:{tag} without the image_tag suppression declared "
        f"for the same upstream image by {', '.join(accepted[(image, tag)])}"
        for (image, tag), owners in sorted(running.items())
        if (image, tag) in accepted
        for owner in owners
        if owner not in accepted[(image, tag)]
    ]


class TestCveSuppressions(unittest.TestCase):
    def test_every_suppression_is_justified_and_dated(self) -> None:
        today = dt.datetime.now(tz=dt.UTC).date()
        found = []
        for path in sorted(
            (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
        ):
            text = read_text(str(path))
            if "suppressions:" in text or "unmatched_os:" in text:
                found += problems(text, str(path.relative_to(PROJECT_ROOT)), today)
        self.assertEqual(found, [], "\n".join(found))

    def test_services_on_one_upstream_image_tag_share_its_suppression(self) -> None:
        services = {
            path.parent.parent.name: load_yaml_str(read_text(str(path)))
            for path in sorted(
                (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
            )
        }
        found = unshared_image_tags(services)
        self.assertEqual(found, [], "\n".join(found))


TODAY = dt.date(2026, 10, 31)
VALID = """\
app:
  image: app
  security:
    suppressions:
      # nocheck: cve the module is not built into the image
      - id: CVE-2026-1234
        until: 2026-11-30
"""


class TestCheckerCases(unittest.TestCase):
    def _problems(self, text: str) -> list[str]:
        return problems(text, f"roles/r/{ROLE_FILE_META_SERVICES}", TODAY)

    def test_a_justified_dated_entry_passes(self) -> None:
        self.assertEqual(self._problems(VALID), [])

    def test_an_entry_without_a_marker_fails(self) -> None:
        text = VALID.replace(
            "      # nocheck: cve the module is not built into the image\n", ""
        )
        self.assertIn("has no # nocheck: cve <reason> marker", self._problems(text)[0])

    def test_a_marker_without_a_reason_fails(self) -> None:
        text = VALID.replace("cve the module is not built into the image", "cve")
        self.assertIn("gives no reason", self._problems(text)[0])

    def test_a_malformed_id_fails(self) -> None:
        text = VALID.replace("CVE-2026-1234", "CVE-26-1")
        self.assertIn("is no CVE-YYYY-NNNN id", self._problems(text)[0])

    def test_a_missing_until_fails(self) -> None:
        text = VALID.replace("        until: 2026-11-30\n", "")
        self.assertIn("until is required", self._problems(text)[0])

    def test_a_past_until_fails(self) -> None:
        text = VALID.replace("2026-11-30", "2026-10-30")
        self.assertIn("expired on 2026-10-30", self._problems(text)[0])

    def test_an_until_after_the_latest_allowed_day_fails(self) -> None:
        text = VALID.replace("2026-11-30", "2026-12-01")
        self.assertIn(
            "until 2026-12-01 lies after the latest allowed day 2026-11-30",
            self._problems(text)[0],
        )

    def test_an_unmarked_entry_that_starts_with_until_fails(self) -> None:
        text = VALID.replace(
            "      # nocheck: cve the module is not built into the image\n"
            "      - id: CVE-2026-1234\n"
            "        until: 2026-11-30\n",
            "      - until: 2026-11-30\n        id: CVE-2026-1234\n",
        )
        self.assertIn("has no # nocheck: cve <reason> marker", self._problems(text)[0])

    def test_a_marker_for_another_rule_does_not_count(self) -> None:
        text = VALID.replace("nocheck: cve", "nocheck: url")
        self.assertIn("has no # nocheck: cve <reason> marker", self._problems(text)[0])

    def test_an_image_tag_of_the_current_version_passes(self) -> None:
        self.assertEqual(self._problems(TAGGED), [])

    def test_an_image_tag_of_an_older_version_fails(self) -> None:
        text = TAGGED.replace('version: "2.18.6"', 'version: "2.18.7"')
        self.assertIn(
            "image tag 2.18.6 does not match its version '2.18.7'",
            self._problems(text)[0],
        )

    def test_an_image_tag_without_a_version_fails(self) -> None:
        text = TAGGED.replace('  version: "2.18.6"\n', "")
        self.assertIn("does not match its version None", self._problems(text)[0])

    def test_an_unmarked_image_tag_entry_fails(self) -> None:
        text = TAGGED.replace(
            "      # nocheck: cve upstream ships no rebuild yet\n", ""
        )
        self.assertIn("has no # nocheck: cve <reason> marker", self._problems(text)[0])

    def test_an_expired_image_tag_entry_fails(self) -> None:
        text = TAGGED.replace("2026-11-30", "2026-10-30")
        self.assertIn("image tag 2.18.6 expired on 2026-10-30", self._problems(text)[0])

    def test_a_dated_unmatched_os_entry_passes(self) -> None:
        self.assertEqual(self._problems(UNMATCHED), [])

    def test_an_expired_unmatched_os_entry_fails(self) -> None:
        text = UNMATCHED.replace("2026-11-30", "2026-10-30")
        self.assertEqual(
            self._problems(text),
            [f"{UNMATCHED_SUBJECT} expired on 2026-10-30"],
        )

    def test_an_unmatched_os_entry_after_the_latest_allowed_day_fails(self) -> None:
        text = UNMATCHED.replace("2026-11-30", "2026-12-01")
        late = "until 2026-12-01 lies after the latest allowed day 2026-11-30"
        self.assertEqual(self._problems(text), [f"{UNMATCHED_SUBJECT} {late}"])


UNMATCHED = """\
trivy:
  image: trivy
  unmatched_os:
    - name: centos
      version: "10"
      until: 2026-11-30
"""
UNMATCHED_SUBJECT = f"roles/r/{ROLE_FILE_META_SERVICES}: trivy unmatched_os centos 10"


TAGGED = """\
app:
  image: app
  version: "2.18.6"
  security:
    suppressions:
      # nocheck: cve upstream ships no rebuild yet
      - image_tag: "2.18.6"
        until: 2026-11-30
"""
UNTAGGED = """\
app:
  image: app
  version: "2.18.6"
"""


class TestSiblingImageTagCases(unittest.TestCase):
    def _found(self, **roles: str) -> list[str]:
        return unshared_image_tags(
            {role: load_yaml_str(text) for role, text in roles.items()}
        )

    def test_siblings_that_both_suppress_the_tag_pass(self) -> None:
        self.assertEqual(self._found(a=TAGGED, b=TAGGED), [])

    def test_a_sibling_without_the_tag_suppression_fails(self) -> None:
        self.assertEqual(
            self._found(a=TAGGED, b=UNTAGGED),
            [
                (
                    "b:app runs app:2.18.6 without the image_tag suppression declared "
                    "for the same upstream image by a:app"
                )
            ],
        )

    def test_a_custom_build_on_the_same_tag_is_its_own_image(self) -> None:
        custom = UNTAGGED.replace("  image: app\n", "  image: app\n  custom: true\n")
        self.assertEqual(self._found(a=TAGGED, b=custom), [])

    def test_a_sibling_on_another_tag_is_not_compared(self) -> None:
        other = UNTAGGED.replace("2.18.6", "2.18.7")
        self.assertEqual(self._found(a=TAGGED, b=other), [])


if __name__ == "__main__":
    unittest.main()
