from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

README = PROJECT_ROOT / "roles" / "web-svc-logout" / "README.md"
SECTION = "## Back-channel logout per role"
COLUMNS = 6
NO_FLAVOR = "-"
ROW = re.compile(r"^\| `(?P<role>[a-z0-9-]+)` \|(?P<cells>.*)\|$")
ANSWER = re.compile(r"^(yes|no)\b", re.IGNORECASE)
PENDING = re.compile(r"to\s+verify|\btbd\b", re.IGNORECASE)


def readme_rows(source: str) -> dict[str, list[str]]:
    """Return the cells of every row of the back-channel table, keyed by role.

    Args:
        source: the README's text.
    """
    section = source.split(SECTION, 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        match = ROW.match(line.strip())
        if match:
            cells = [cell.strip() for cell in match.group("cells").split(" | ")]
            rows[match.group("role")] = [match.group("role"), *cells]
    return rows


def sso_flavors() -> dict[str, str]:
    flavors = {}
    for path in sorted(PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_META_SERVICES}")):
        services = load_yaml_any(str(path)) or {}
        sso = services.get("sso") if isinstance(services, dict) else None
        if isinstance(sso, dict):
            flavors[path.parts[-3]] = str(sso.get("flavor", NO_FLAVOR))
    return flavors


def table_findings(rows: dict[str, list[str]], flavors: dict[str, str]) -> list[str]:
    """Return what keeps the table from holding one complete row per SSO role.

    Args:
        rows: the README rows, keyed by role.
        flavors: the SSO flavor of every role with an ``sso`` service.
    """
    findings = [f"{role}: no row" for role in sorted(set(flavors) - set(rows))]
    findings += [f"{role}: no sso service" for role in sorted(set(rows) - set(flavors))]
    for role in sorted(set(rows) & set(flavors)):
        cells = rows[role]
        if len(cells) != COLUMNS or not all(cells):
            findings.append(f"{role}: expected {COLUMNS} filled cells")
        elif cells[1] != flavors[role]:
            findings.append(f"{role}: flavor {cells[1]} is not {flavors[role]}")
    return findings


def answer_findings(rows: dict[str, list[str]]) -> list[str]:
    """Return the rows whose back-channel cell answers neither yes nor no, and every pending cell.

    Args:
        rows: the README rows, keyed by role; a cell is pending when it holds
            "to verify" or "TBD" in any case.
    """
    findings = []
    for role, cells in sorted(rows.items()):
        if len(cells) != COLUMNS:
            continue
        if not ANSWER.match(cells[2]):
            findings.append(
                f"{role}: back-channel cell {cells[2]!r} answers neither yes nor no"
            )
        findings.extend(
            f"{role}: cell {index} is left pending"
            for index, cell in enumerate(cells)
            if PENDING.search(cell)
        )
    return findings


class TestBackchannelTableCoversEverySsoRole(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = readme_rows(read_text(str(README)))
        self.flavors = sso_flavors()

    def test_the_table_holds_one_row_per_sso_role_with_its_flavor(self) -> None:
        self.assertEqual(table_findings(self.rows, self.flavors), [])

    def test_a_missing_role_and_a_wrong_flavor_are_caught(self) -> None:
        rows = dict(self.rows)
        del rows["web-app-matrix"]
        rows["web-app-stalwart"] = [
            "web-app-stalwart",
            "oauth2",
            *rows["web-app-stalwart"][2:],
        ]
        self.assertEqual(
            table_findings(rows, self.flavors),
            [
                "web-app-matrix: no row",
                f"web-app-stalwart: flavor oauth2 is not {self.flavors['web-app-stalwart']}",
            ],
        )

    def test_every_row_answers_yes_or_no_and_leaves_nothing_to_verify(self) -> None:
        self.assertEqual(answer_findings(self.rows), [])

    def test_a_pending_marker_in_any_cell_and_any_case_is_caught(self) -> None:
        for index in range(1, COLUMNS):
            for marker in ("to verify", "To Verify", "TBD", "yes? TBD"):
                with self.subTest(cell=index, marker=marker):
                    rows = dict(self.rows)
                    cells = list(rows["web-app-grafana"])
                    cells[index] = marker
                    rows["web-app-grafana"] = cells
                    expected = [f"web-app-grafana: cell {index} is left pending"]
                    if index == 2 and not marker.startswith("yes"):
                        expected.insert(
                            0,
                            f"web-app-grafana: back-channel cell {marker!r} "
                            "answers neither yes nor no",
                        )
                    self.assertEqual(answer_findings(rows), expected)

    def test_an_answer_in_another_case_still_counts(self) -> None:
        rows = dict(self.rows)
        cells = list(rows["web-app-grafana"])
        cells[2] = "No, " + cells[2].removeprefix("no, ")
        rows["web-app-grafana"] = cells
        self.assertEqual(answer_findings(rows), [])


if __name__ == "__main__":
    unittest.main()
