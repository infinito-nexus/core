from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from cli.meta.roles.applications.complexity.cli import main
from cli.meta.roles.applications.complexity.model import compute_complexity_rows
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN


def _mk_role(
    roles_dir: Path,
    role: str,
    services_yaml: str,
) -> None:
    role_dir = roles_dir / role
    vars_file = role_dir / ROLE_FILE_VARS_MAIN
    services_file = role_dir / ROLE_FILE_META_SERVICES
    vars_file.parent.mkdir(parents=True, exist_ok=True)
    services_file.parent.mkdir(parents=True, exist_ok=True)
    vars_file.write_text(f"application_id: {role}\n", encoding="utf-8")
    services_file.write_text(services_yaml, encoding="utf-8")


class TestComplexityRows(unittest.TestCase):
    def _build_chain_roles(self, roles_dir: Path) -> None:
        # r1: provider only
        _mk_role(
            roles_dir,
            "r1",
            "r1:\n  enabled: true\n  shared: true\n",
        )
        # r2: provider, consumes r1 with literal-true flags
        _mk_role(
            roles_dir,
            "r2",
            (
                "r2:\n  enabled: true\n  shared: true\n"
                "r1:\n  enabled: true\n  shared: true\n"
            ),
        )
        # r3: provider, consumes r2 with literal-true flags
        _mk_role(
            roles_dir,
            "r3",
            (
                "r3:\n  enabled: true\n  shared: true\n"
                "r2:\n  enabled: true\n  shared: true\n"
            ),
        )

    def test_chain_default_sort_by_points(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_chain_roles(roles_dir)

            rows = compute_complexity_rows(roles_dir)
            rows.sort(key=lambda r: (r[1], r[0]))

            self.assertEqual([r[0] for r in rows], ["r1", "r2", "r3"])
            self.assertEqual([r[1] for r in rows], [0, 1, 2])
            self.assertEqual(rows[0][2], [])
            self.assertEqual(rows[1][2], ["r1"])
            # r3 -> r2 -> r1 (BFS reaches r2 first, then r1)
            self.assertEqual(rows[2][2], ["r2", "r1"])

            # Reverse direction (consumers): r1 is embedded by r2 and
            # transitively by r3; r2 is embedded by r3; r3 has no consumer.
            row_map = {row[0]: row for row in rows}
            self.assertEqual(row_map["r1"][3], 2)
            self.assertEqual(row_map["r1"][4], ["r2", "r3"])
            self.assertEqual(row_map["r2"][3], 1)
            self.assertEqual(row_map["r2"][4], ["r3"])
            self.assertEqual(row_map["r3"][3], 0)
            self.assertEqual(row_map["r3"][4], [])

            # Direct (one-hop) fields. r3 -> r2 transitively reaches r1,
            # but r3's *direct* embeds is just r2; symmetrically r1's
            # *direct* consumers is r2 only (r3 reaches it via r2).
            self.assertEqual(row_map["r1"][5], 0)
            self.assertEqual(row_map["r1"][6], [])
            self.assertEqual(row_map["r1"][7], 1)
            self.assertEqual(row_map["r1"][8], ["r2"])
            self.assertEqual(row_map["r2"][5], 1)
            self.assertEqual(row_map["r2"][6], ["r1"])
            self.assertEqual(row_map["r2"][7], 1)
            self.assertEqual(row_map["r2"][8], ["r3"])
            self.assertEqual(row_map["r3"][5], 1)
            self.assertEqual(row_map["r3"][6], ["r2"])
            self.assertEqual(row_map["r3"][7], 0)
            self.assertEqual(row_map["r3"][8], [])

            # Total = embeds + consumers + embeds_direct + consumers_direct.
            # r1: 0 + 2 + 0 + 1 = 3, r2: 1 + 1 + 1 + 1 = 4, r3: 2 + 0 + 1 + 0 = 3.
            self.assertEqual(row_map["r1"][9], 3)
            self.assertEqual(row_map["r2"][9], 4)
            self.assertEqual(row_map["r3"][9], 3)

    def test_group_names_flag_toggles_dynamic_truth(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()

            # provider
            _mk_role(
                roles_dir,
                "r1",
                "r1:\n  enabled: true\n  shared: true\n",
            )
            # consumer using the dynamic-flag form
            _mk_role(
                roles_dir,
                "r2",
                (
                    "r2:\n  enabled: true\n  shared: true\n"
                    "r1:\n"
                    "  enabled: \"{{ 'r1' in group_names }}\"\n"
                    "  shared: \"{{ 'r1' in group_names }}\"\n"
                ),
            )

            with_groups = compute_complexity_rows(roles_dir, include_group_names=True)
            without_groups = compute_complexity_rows(
                roles_dir, include_group_names=False
            )

            with_groups_map = {row[0]: row[1] for row in with_groups}
            without_groups_map = {row[0]: row[1] for row in without_groups}

            self.assertEqual(with_groups_map["r2"], 1)
            self.assertEqual(without_groups_map["r2"], 0)
            self.assertEqual(with_groups_map["r1"], 0)
            self.assertEqual(without_groups_map["r1"], 0)

    def test_self_is_not_counted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()

            # r1 declares itself shared+enabled (provider role).
            # Its own primary entry MUST NOT inflate its dep count.
            _mk_role(
                roles_dir,
                "r1",
                "r1:\n  enabled: true\n  shared: true\n",
            )

            rows = compute_complexity_rows(roles_dir)
            row_map = {row[0]: row for row in rows}
            self.assertEqual(row_map["r1"][1], 0)
            self.assertEqual(row_map["r1"][2], [])

    def test_level_caps_recursion_depth(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_chain_roles(roles_dir)

            rows_full = compute_complexity_rows(roles_dir)
            rows_l1 = compute_complexity_rows(roles_dir, max_level=1)
            rows_l2 = compute_complexity_rows(roles_dir, max_level=2)

            full_map = {row[0]: row for row in rows_full}
            l1_map = {row[0]: row for row in rows_l1}
            l2_map = {row[0]: row for row in rows_l2}

            # r3 -> r2 -> r1: full=2, level1=1 (just r2), level2=2 (r2, r1)
            self.assertEqual(full_map["r3"][1], 2)
            self.assertEqual(full_map["r3"][2], ["r2", "r1"])

            self.assertEqual(l1_map["r3"][1], 1)
            self.assertEqual(l1_map["r3"][2], ["r2"])

            self.assertEqual(l2_map["r3"][1], 2)
            self.assertEqual(l2_map["r3"][2], ["r2", "r1"])

            # r2 has only r1 as a direct dep -- level 1 already covers it.
            self.assertEqual(l1_map["r2"][2], ["r1"])

            # Reverse direction respects the same depth cap. r1 is
            # consumed by r2 (depth 1) and transitively by r3 (depth 2).
            self.assertEqual(full_map["r1"][3], 2)
            self.assertEqual(full_map["r1"][4], ["r2", "r3"])

            self.assertEqual(l1_map["r1"][3], 1)
            self.assertEqual(l1_map["r1"][4], ["r2"])

            self.assertEqual(l2_map["r1"][3], 2)
            self.assertEqual(l2_map["r1"][4], ["r2", "r3"])

    def test_non_application_roles_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()

            # role without vars/main.yml -> not an application -> skipped
            non_app_services = roles_dir / "non-app" / ROLE_FILE_META_SERVICES
            non_app_services.parent.mkdir(parents=True)
            non_app_services.write_text(
                "x:\n  enabled: true\n  shared: true\n", encoding="utf-8"
            )

            _mk_role(
                roles_dir,
                "r1",
                "r1:\n  enabled: true\n  shared: true\n",
            )

            rows = compute_complexity_rows(roles_dir)
            names = [row[0] for row in rows]
            self.assertEqual(names, ["r1"])

    def test_format_string_prints_only_role_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_chain_roles(roles_dir)

            buf = io.StringIO()
            with (
                mock.patch(
                    "cli.meta.roles.applications.complexity.cli.PROJECT_ROOT",
                    Path(td),
                ),
                redirect_stdout(buf),
            ):
                rc = main(["--format", "string", "--sort", "name"])

            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().split(), ["r1", "r2", "r3"])

    def _build_mutual_roles(self, roles_dir: Path) -> None:
        # r1 and r2 embed each other -> identical {name} ∪ services set
        # -> identical base. r3 stands alone with its own base.
        _mk_role(
            roles_dir,
            "r1",
            (
                "r1:\n  enabled: true\n  shared: true\n"
                "r2:\n  enabled: true\n  shared: true\n"
            ),
        )
        _mk_role(
            roles_dir,
            "r2",
            (
                "r2:\n  enabled: true\n  shared: true\n"
                "r1:\n  enabled: true\n  shared: true\n"
            ),
        )
        _mk_role(
            roles_dir,
            "r3",
            "r3:\n  enabled: true\n  shared: true\n",
        )

    def test_base_groups_same_service_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_mutual_roles(roles_dir)

            rows = compute_complexity_rows(roles_dir)
            row_map = {row.name: row for row in rows}

            self.assertEqual(row_map["r1"].base, row_map["r2"].base)
            self.assertNotEqual(row_map["r1"].base, row_map["r3"].base)
            self.assertEqual(row_map["r1"].siblings, ["r2"])
            self.assertEqual(row_map["r2"].siblings, ["r1"])
            self.assertEqual(row_map["r3"].siblings, [])

    def test_unique_hides_same_base_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_mutual_roles(roles_dir)

            buf = io.StringIO()
            with (
                mock.patch(
                    "cli.meta.roles.applications.complexity.cli.PROJECT_ROOT",
                    Path(td),
                ),
                redirect_stdout(buf),
            ):
                rc = main(["--format", "string", "--sort", "name", "--unique"])

            self.assertEqual(rc, 0)
            # r1/r2 share a base -> only the first by name survives; r3 stays.
            self.assertEqual(buf.getvalue().split(), ["r1", "r3"])


if __name__ == "__main__":
    unittest.main()
