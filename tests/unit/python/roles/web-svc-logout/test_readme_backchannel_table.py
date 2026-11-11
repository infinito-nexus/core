from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.roles.custom import is_custom
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLES_DIR = PROJECT_ROOT / "roles"
README = ROLES_DIR / "web-svc-logout" / "README.md"
SECTION = "## Back-channel logout per role"
COLUMNS = 6
NO_FLAVOR = "-"
BACKCHANNEL = "backchannel"
DECLARED = ("logout", "endpoint", "documentation", "session")
DECLARE_HINT = (
    f"declare sso.{BACKCHANNEL} with {', '.join(DECLARED)} in the role's own "
    f"{ROLE_FILE_META_SERVICES}"
)
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


def sso_services(roles_dir: Path) -> dict[str, dict[str, Any]]:
    """Return the ``sso`` service of every role that declares one, keyed by role.

    Args:
        roles_dir: the directory holding one subdirectory per role.
    """
    services_by_role = {}
    for path in sorted(roles_dir.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        services = load_yaml_any(str(path)) or {}
        sso = services.get("sso") if isinstance(services, dict) else None
        if isinstance(sso, dict):
            services_by_role[path.parts[-3]] = sso
    return services_by_role


def _flavor(sso: dict[str, Any]) -> str:
    return str(sso.get("flavor", NO_FLAVOR))


def _cell(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _declares(role: str, sso: dict[str, Any]) -> bool:
    return is_custom(role) and BACKCHANNEL in sso


def _unreadable(role: str, sso: dict[str, Any]) -> list[str]:
    """Return why a custom role's ``sso.backchannel`` yields no row.

    Args:
        role: the custom role.
        sso: its ``sso`` service, which carries ``backchannel``.
    """
    declaration = sso[BACKCHANNEL]
    if not isinstance(declaration, dict):
        return [f"{role}: sso.{BACKCHANNEL} must map {', '.join(DECLARED)}"]
    return [
        f"{role}: sso.{BACKCHANNEL}.{key} must be a quoted string"
        for key in DECLARED
        if key in declaration and not isinstance(declaration[key], str)
    ]


def sso_flavors(sso_by_role: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Return the SSO flavor of every role the table must hold a row for.

    Args:
        sso_by_role: the ``sso`` service of every role that declares one.

    Returns:
        The flavor keyed by role; a custom role whose ``sso.backchannel``
        yields no row is left to :func:`declaration_findings`.
    """
    return {
        role: _flavor(sso)
        for role, sso in sso_by_role.items()
        if not (_declares(role, sso) and _unreadable(role, sso))
    }


def declared_rows(sso_by_role: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Return the table row each custom role declares under ``sso.backchannel``.

    Args:
        sso_by_role: the ``sso`` service of every role that declares one.

    Returns:
        The role, its ``sso.flavor`` and one cell per key of ``DECLARED``,
        keyed by role; a missing key leaves its cell empty. A core role's
        declaration and an unreadable one yield no row.
    """
    return {
        role: [
            role,
            _flavor(sso),
            *(_cell(sso[BACKCHANNEL].get(key)) for key in DECLARED),
        ]
        for role, sso in sso_by_role.items()
        if _declares(role, sso) and not _unreadable(role, sso)
    }


def table_rows(
    readme: dict[str, list[str]], sso_by_role: dict[str, dict[str, Any]]
) -> dict[str, list[str]]:
    """Return the README rows with every custom role's declared row on top.

    Args:
        readme: the README rows, keyed by role.
        sso_by_role: the ``sso`` service of every role that declares one.
    """
    return {**readme, **declared_rows(sso_by_role)}


def declaration_findings(sso_by_role: dict[str, dict[str, Any]]) -> list[str]:
    """Return every ``sso.backchannel`` a core role declares and every malformed one.

    Args:
        sso_by_role: the ``sso`` service of every role that declares one.
    """
    findings = []
    for role, sso in sorted(sso_by_role.items()):
        if BACKCHANNEL not in sso:
            continue
        if not is_custom(role):
            findings.append(
                f"{role}: a core role keeps its row in {README.relative_to(PROJECT_ROOT)}; "
                f"drop sso.{BACKCHANNEL}"
            )
            continue
        findings.extend(_unreadable(role, sso))
        declaration = sso[BACKCHANNEL]
        if isinstance(declaration, dict):
            findings.extend(
                f"{role}: sso.{BACKCHANNEL}.{key} is no column of the table"
                for key in sorted(str(key) for key in set(declaration) - set(DECLARED))
            )
    return findings


def _missing(role: str) -> str:
    return f"{role}: no row; {DECLARE_HINT}" if is_custom(role) else f"{role}: no row"


def table_findings(rows: dict[str, list[str]], flavors: dict[str, str]) -> list[str]:
    """Return what keeps the table from holding one complete row per SSO role.

    Args:
        rows: the table rows, keyed by role.
        flavors: the SSO flavor of every role with an ``sso`` service.
    """
    findings = [_missing(role) for role in sorted(set(flavors) - set(rows))]
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
        rows: the table rows, keyed by role; a cell is pending when it holds
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


CUSTOM_ROLE = "web-app-cst-quality"
CUSTOM_DECLARATION = {
    "logout": (
        "no, native OIDC without a back-channel logout endpoint: /account/logout "
        "ends the session front-channel through the Keycloak end-session endpoint"
    ),
    "endpoint": "-",
    "documentation": "-",
    "session": "until /account/logout or the Keycloak session ends",
}


def _with_declaration(sso: dict[str, Any], declaration: Any) -> dict[str, Any]:
    return {**sso, BACKCHANNEL: declaration}


class TestBackchannelTableCoversEverySsoRole(unittest.TestCase):
    def setUp(self) -> None:
        self.sso = sso_services(ROLES_DIR)
        self.flavors = sso_flavors(self.sso)
        self.rows = table_rows(readme_rows(read_text(str(README))), self.sso)

    def test_the_table_holds_one_row_per_sso_role_with_its_flavor(self) -> None:
        self.assertEqual(table_findings(self.rows, self.flavors), [])

    def test_every_backchannel_declaration_is_a_custom_roles_own_row(self) -> None:
        self.assertEqual(declaration_findings(self.sso), [])

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


class TestCustomRoleDeclaresItsOwnRow(unittest.TestCase):
    def setUp(self) -> None:
        self.readme = readme_rows(read_text(str(README)))
        self.sso = {
            **{
                role: sso
                for role, sso in sso_services(ROLES_DIR).items()
                if not is_custom(role)
            },
            CUSTOM_ROLE: {
                "enabled": True,
                "flavor": "oidc",
                BACKCHANNEL: dict(CUSTOM_DECLARATION),
            },
        }

    def findings(self, sso: dict[str, dict[str, Any]]) -> list[str]:
        rows = table_rows(self.readme, sso)
        return (
            table_findings(rows, sso_flavors(sso))
            + answer_findings(rows)
            + declaration_findings(sso)
        )

    def test_a_declared_row_stands_in_for_the_readme_row(self) -> None:
        self.assertNotIn(CUSTOM_ROLE, self.readme)
        self.assertEqual(
            table_rows(self.readme, self.sso)[CUSTOM_ROLE],
            [CUSTOM_ROLE, "oidc", *CUSTOM_DECLARATION.values()],
        )
        self.assertEqual(self.findings(self.sso), [])

    def test_a_custom_role_without_a_declaration_has_no_row(self) -> None:
        sso = dict(self.sso)
        sso[CUSTOM_ROLE] = {"enabled": True, "flavor": "oidc"}
        self.assertEqual(self.findings(sso), [f"{CUSTOM_ROLE}: no row; {DECLARE_HINT}"])

    def test_a_declared_row_meets_every_check_of_a_readme_row(self) -> None:
        cases = {
            "logout": (
                "maybe",
                [
                    f"{CUSTOM_ROLE}: back-channel cell 'maybe' answers neither yes nor no"
                ],
            ),
            "endpoint": ("TBD", [f"{CUSTOM_ROLE}: cell 3 is left pending"]),
            "session": (
                "",
                [f"{CUSTOM_ROLE}: expected {COLUMNS} filled cells"],
            ),
        }
        for key, (value, expected) in cases.items():
            with self.subTest(key=key):
                sso = dict(self.sso)
                sso[CUSTOM_ROLE] = _with_declaration(
                    sso[CUSTOM_ROLE], {**CUSTOM_DECLARATION, key: value}
                )
                self.assertEqual(self.findings(sso), expected)

    def test_the_flavor_cell_is_the_roles_own_sso_flavor(self) -> None:
        sso = dict(self.sso)
        sso[CUSTOM_ROLE] = {**sso[CUSTOM_ROLE], "flavor": "oauth2"}
        self.assertEqual(table_rows(self.readme, sso)[CUSTOM_ROLE][1], "oauth2")
        self.assertEqual(self.findings(sso), [])

    def test_a_malformed_declaration_is_caught(self) -> None:
        cases = {
            "no mapping": (
                "no",
                [f"{CUSTOM_ROLE}: sso.{BACKCHANNEL} must map {', '.join(DECLARED)}"],
            ),
            "a missing key": (
                {
                    key: value
                    for key, value in CUSTOM_DECLARATION.items()
                    if key != "session"
                },
                [f"{CUSTOM_ROLE}: expected {COLUMNS} filled cells"],
            ),
            "unknown key": (
                {**CUSTOM_DECLARATION, "flavor": "oidc"},
                [f"{CUSTOM_ROLE}: sso.{BACKCHANNEL}.flavor is no column of the table"],
            ),
        }
        for case, (declaration, expected) in cases.items():
            with self.subTest(case=case):
                sso = dict(self.sso)
                sso[CUSTOM_ROLE] = _with_declaration(sso[CUSTOM_ROLE], declaration)
                self.assertEqual(self.findings(sso), expected)

    def test_a_value_that_is_no_string_is_named_and_hides_its_cell_findings(
        self,
    ) -> None:
        cases = {
            "logout": False,
            "endpoint": 8080,
            "documentation": ["not", "a", "string"],
            "session": None,
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                sso = dict(self.sso)
                sso[CUSTOM_ROLE] = _with_declaration(
                    sso[CUSTOM_ROLE], {**CUSTOM_DECLARATION, key: value}
                )
                self.assertEqual(
                    self.findings(sso),
                    [f"{CUSTOM_ROLE}: sso.{BACKCHANNEL}.{key} must be a quoted string"],
                )

    def test_an_unquoted_yaml_answer_and_port_are_named(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            services = Path(root) / CUSTOM_ROLE / ROLE_FILE_META_SERVICES
            services.parent.mkdir(parents=True)
            services.write_text(
                "sso:\n"
                "  enabled: true\n"
                "  flavor: oidc\n"
                f"  {BACKCHANNEL}:\n"
                "    logout: no\n"
                "    endpoint: 8080\n"
                '    documentation: "-"\n'
                "    session: until the Keycloak session ends\n",
                encoding="utf-8",
            )
            sso = {**self.sso, **sso_services(Path(root))}
        self.assertEqual(
            self.findings(sso),
            [
                f"{CUSTOM_ROLE}: sso.{BACKCHANNEL}.logout must be a quoted string",
                f"{CUSTOM_ROLE}: sso.{BACKCHANNEL}.endpoint must be a quoted string",
            ],
        )

    def test_a_core_role_cannot_trade_its_readme_row_for_a_declaration(self) -> None:
        readme = dict(self.readme)
        del readme["web-app-grafana"]
        sso = dict(self.sso)
        sso["web-app-grafana"] = _with_declaration(
            sso["web-app-grafana"], dict(CUSTOM_DECLARATION)
        )
        rows = table_rows(readme, sso)
        self.assertNotIn("web-app-grafana", rows)
        self.assertEqual(
            table_findings(rows, sso_flavors(sso)) + declaration_findings(sso),
            [
                "web-app-grafana: no row",
                (
                    "web-app-grafana: a core role keeps its row in "
                    f"roles/web-svc-logout/README.md; drop sso.{BACKCHANNEL}"
                ),
            ],
        )

    def test_the_declaration_is_read_from_the_roles_own_services_file(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            services = Path(root) / CUSTOM_ROLE / ROLE_FILE_META_SERVICES
            dump_yaml(
                services,
                {
                    "sso": {
                        "enabled": True,
                        "flavor": "oidc",
                        BACKCHANNEL: CUSTOM_DECLARATION,
                    }
                },
            )
            self.assertEqual(
                declared_rows(sso_services(Path(root))),
                {CUSTOM_ROLE: [CUSTOM_ROLE, "oidc", *CUSTOM_DECLARATION.values()]},
            )


if __name__ == "__main__":
    unittest.main()
