from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from cli.meta.roles.applications.complexity.cli import (
    _mark_covered,
    main,
    parse_sort_spec,
)
from cli.meta.roles.applications.complexity.model import (
    ComplexityRow,
    compute_complexity_rows,
    compute_variant_complexity_rows,
)
from cli.meta.roles.applications.complexity.render import (
    _bool_cell,
    _dwidth,
    _header,
    _lifecycle_cell,
)
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_TESTS,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)


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


def _mk_variants(roles_dir: Path, role: str, variants_yaml: str) -> None:
    path = roles_dir / role / ROLE_FILE_META_VARIANTS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(variants_yaml, encoding="utf-8")


class TestComplexityRows(unittest.TestCase):
    def _build_chain_roles(self, roles_dir: Path) -> None:
        _mk_role(
            roles_dir,
            "r1",
            "r1:\n  enabled: true\n  shared: true\n",
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
            self.assertEqual(rows[2][2], ["r2", "r1"])

            row_map = {row[0]: row for row in rows}
            self.assertEqual(row_map["r1"][3], 2)
            self.assertEqual(row_map["r1"][4], ["r2", "r3"])
            self.assertEqual(row_map["r2"][3], 1)
            self.assertEqual(row_map["r2"][4], ["r3"])
            self.assertEqual(row_map["r3"][3], 0)
            self.assertEqual(row_map["r3"][4], [])

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

            self.assertEqual(row_map["r1"][9], 3)
            self.assertEqual(row_map["r2"][9], 4)
            self.assertEqual(row_map["r3"][9], 3)

    def test_group_names_flag_toggles_dynamic_truth(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()

            _mk_role(
                roles_dir,
                "r1",
                "r1:\n  enabled: true\n  shared: true\n",
            )
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

            self.assertEqual(full_map["r3"][1], 2)
            self.assertEqual(full_map["r3"][2], ["r2", "r1"])

            self.assertEqual(l1_map["r3"][1], 1)
            self.assertEqual(l1_map["r3"][2], ["r2"])

            self.assertEqual(l2_map["r3"][1], 2)
            self.assertEqual(l2_map["r3"][2], ["r2", "r1"])

            self.assertEqual(l1_map["r2"][2], ["r1"])

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

            self.assertEqual(row_map["r1"].dna, row_map["r2"].dna)
            self.assertNotEqual(row_map["r1"].dna, row_map["r3"].dna)
            self.assertEqual(row_map["r1"].siblings, ["r2"])
            self.assertEqual(row_map["r2"].siblings, ["r1"])
            self.assertEqual(row_map["r3"].siblings, [])

    def test_clone_marks_every_dna_sibling_but_the_heaviest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_mutual_roles(roles_dir)

            row_map = {r.name: r for r in compute_complexity_rows(roles_dir)}
            group = [row_map["r1"], row_map["r2"]]
            original = max(group, key=lambda r: (r.weight, r.name))
            for row in group:
                self.assertEqual(row.clone, row.name != original.name)
            self.assertFalse(row_map["r3"].clone)

    def test_clone_filter_keeps_one_representative_per_dna(self) -> None:
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
                rc = main(
                    [
                        "--format",
                        "string",
                        "--sort",
                        "name",
                        "--filter",
                        "clone == false",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertEqual(len(buf.getvalue().split()), 2)


class TestComposeSwarmColumns(unittest.TestCase):
    def _build(self, roles_dir: Path) -> None:
        _mk_role(
            roles_dir,
            "r1",
            "r1:\n  enabled: true\n  shared: true\n",
        )
        _mk_role(
            roles_dir,
            "r2",
            (
                "r2:\n  enabled: true\n  shared: true\n"
                "r1:\n  enabled: true\n  shared: true\n"
            ),
        )
        r2_compose = roles_dir / "r2" / ROLE_FILE_TEMPL_COMPOSE
        r2_compose.parent.mkdir(parents=True, exist_ok=True)
        r2_compose.write_text("services: {}\n", encoding="utf-8")
        _mk_variants(
            roles_dir,
            "r2",
            ("- {}\n- services:\n    r1:\n      enabled: false\n      shared: false\n"),
        )

    def test_tested_role_is_compose_and_swarm(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)

            with mock.patch(
                "cli.meta.roles.applications.complexity.model._tested_apps",
                return_value={"r1", "r2"},
            ):
                rows = {r.name: r for r in compute_complexity_rows(roles_dir)}
            self.assertTrue(rows["r2"].compose)
            self.assertTrue(rows["r2"].swarm)

    def test_untested_role_is_neither(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)

            with mock.patch(
                "cli.meta.roles.applications.complexity.model._tested_apps",
                return_value=set(),
            ):
                rows = {r.name: r for r in compute_complexity_rows(roles_dir)}
            self.assertFalse(rows["r2"].compose)
            self.assertFalse(rows["r2"].swarm)

    def test_swarm_runs_every_variant_including_all_off(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)

            with mock.patch(
                "cli.meta.roles.applications.complexity.model._tested_apps",
                return_value={"r1", "r2"},
            ):
                r2 = {
                    r.variant: r
                    for r in compute_variant_complexity_rows(roles_dir)
                    if r.name == "r2"
                }
            self.assertTrue(r2[0].swarm)
            self.assertTrue(r2[1].swarm)
            self.assertTrue(r2[0].compose and r2[1].compose)

    def test_integrated_false_when_variant_disables_every_foreign_service(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)

            with mock.patch(
                "cli.meta.roles.applications.complexity.model._tested_apps",
                return_value={"r1", "r2"},
            ):
                r2 = {
                    r.variant: r
                    for r in compute_variant_complexity_rows(roles_dir)
                    if r.name == "r2"
                }
            self.assertTrue(r2[0].integrated)
            self.assertFalse(r2[1].integrated)


class TestStackColumn(unittest.TestCase):
    def _build(self, roles_dir: Path) -> None:
        _mk_role(
            roles_dir,
            "stack-app",
            "stack-app:\n  enabled: true\n  shared: true\n",
        )
        compose = roles_dir / "stack-app" / ROLE_FILE_TEMPL_COMPOSE
        compose.parent.mkdir(parents=True, exist_ok=True)
        compose.write_text("services: {}\n", encoding="utf-8")
        _mk_role(
            roles_dir,
            "host-app",
            "host-app:\n  enabled: true\n  shared: true\n",
        )

    def test_stack_is_true_only_for_image_bearing_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)

            by_name = {r.name: r for r in compute_complexity_rows(roles_dir)}
            self.assertTrue(by_name["stack-app"].stack)
            self.assertFalse(by_name["host-app"].stack)

    def test_host_column_gates_on_non_stack_and_modes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)
            _mk_role(
                roles_dir,
                "host-off",
                "host-off:\n  enabled: true\n  modes:\n    host:\n      enabled: false\n",
            )

            with mock.patch(
                "cli.meta.roles.applications.complexity.model._tested_apps",
                return_value={"host-app", "host-off", "stack-app"},
            ):
                by_name = {r.name: r for r in compute_complexity_rows(roles_dir)}
            self.assertTrue(by_name["host-app"].host)  # non-stack, default enabled
            self.assertFalse(by_name["stack-app"].host)  # stack roles are never host
            self.assertFalse(by_name["host-off"].host)  # modes.host.enabled: false

    def test_tests_yml_skip_clears_test_columns_but_not_base(self) -> None:
        """meta/tests.yml skip deactivates testing a mode (test_* columns)
        while the base capability columns stay untouched."""
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)
            (roles_dir / "host-app" / ROLE_FILE_META_TESTS).write_text(
                "---\nskip:\n  - host\n", encoding="utf-8"
            )

            with mock.patch(
                "cli.meta.roles.applications.complexity.model._tested_apps",
                return_value={"host-app", "stack-app"},
            ):
                by_name = {r.name: r for r in compute_complexity_rows(roles_dir)}
            self.assertTrue(by_name["host-app"].host)
            self.assertFalse(by_name["host-app"].test_host)
            self.assertTrue(by_name["stack-app"].test_compose)
            self.assertTrue(by_name["stack-app"].compose)

    def test_host_column_gates_on_lifecycle_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)

            with mock.patch(
                "cli.meta.roles.applications.complexity.model._tested_apps",
                return_value=set(),
            ):
                by_name = {r.name: r for r in compute_complexity_rows(roles_dir)}
            self.assertFalse(by_name["host-app"].host)  # outside lifecycle envelope

    def test_symbol_cells_and_headers(self) -> None:
        self.assertEqual(_lifecycle_cell("beta", symbol=True), "🌿")
        self.assertEqual(_lifecycle_cell("eol", symbol=True), "🪦")
        self.assertEqual(_lifecycle_cell("planned", symbol=True), "🧭")
        self.assertEqual(_bool_cell(True, symbol=True), "✅")
        self.assertEqual(_bool_cell(False, symbol=True), "❌")
        self.assertEqual(_header("compose", symbol=True), "🐳")
        self.assertEqual(_bool_cell(True), "true")
        self.assertEqual(_lifecycle_cell("beta"), "beta")
        self.assertEqual(_header("compose", symbol=False), "compose")

    def test_display_width_counts_emoji_as_two(self) -> None:
        """Plain ASCII is 1 cell per char, emoji are 2, and a variation
        selector adds 0 on top of its base emoji."""
        self.assertEqual(_dwidth("ab"), 2)
        self.assertEqual(_dwidth("🐳"), 2)
        self.assertEqual(_dwidth("🛠️"), 2)
        self.assertEqual(_dwidth("✅"), 2)

    def test_all_table_symbols_have_unambiguous_terminal_width(self) -> None:
        """Every table symbol must be a single East-Asian-Wide emoji without a
        variation selector. VS16 sequences on narrow base chars (like the old
        🖥️/➡️/⚖️) render 2 cells in terminals while wcwidth reports 1, which
        shifts every header right of them off its column."""
        import unicodedata

        from cli.meta.roles.applications.complexity.render import (
            _HEADER_SYMBOLS,
            _LIFECYCLE_SYMBOLS,
        )

        symbols = {**_HEADER_SYMBOLS, **_LIFECYCLE_SYMBOLS, "true": "✅", "false": "❌"}
        for name, sym in symbols.items():
            with self.subTest(symbol=name):
                self.assertEqual(
                    unicodedata.east_asian_width(sym[0]),
                    "W",
                    f"{name}={sym!r}: base char is not East-Asian Wide",
                )
                self.assertFalse(
                    any(0xFE00 <= ord(c) <= 0xFE0F for c in sym),
                    f"{name}={sym!r}: contains a variation selector",
                )

    def test_stack_is_per_role_in_variant_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)

            by_name = {r.name: r for r in compute_variant_complexity_rows(roles_dir)}
            self.assertTrue(by_name["stack-app"].stack)
            self.assertFalse(by_name["host-app"].stack)

    def test_filter_by_stack(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)

            buf = io.StringIO()
            with (
                mock.patch(
                    "cli.meta.roles.applications.complexity.cli.PROJECT_ROOT",
                    Path(td),
                ),
                redirect_stdout(buf),
            ):
                rc = main(["--format", "string", "--filter", "stack == true"])

            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().split(), ["stack-app"])

    def test_swarm_is_false_when_stack_is_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build(roles_dir)

            with mock.patch(
                "cli.meta.roles.applications.complexity.model._tested_apps",
                return_value={"stack-app", "host-app"},
            ):
                whole = {r.name: r for r in compute_complexity_rows(roles_dir)}
                per_variant = {
                    r.name: r for r in compute_variant_complexity_rows(roles_dir)
                }
            self.assertFalse(whole["host-app"].stack)
            self.assertFalse(whole["host-app"].swarm)
            self.assertFalse(per_variant["host-app"].swarm)


class TestLifecycleFilter(unittest.TestCase):
    def _build_lifecycle_roles(self, roles_dir: Path) -> None:
        _mk_role(
            roles_dir,
            "alpha-app",
            "alpha-app:\n  enabled: true\n  shared: true\n  lifecycle: alpha\n",
        )
        _mk_role(
            roles_dir,
            "beta-app",
            "beta-app:\n  enabled: true\n  shared: true\n  lifecycle: beta\n",
        )

    def test_lifecycle_is_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_lifecycle_roles(roles_dir)

            by_name = {r.name: r for r in compute_complexity_rows(roles_dir)}
            self.assertEqual(by_name["alpha-app"].lifecycle, "alpha")
            self.assertEqual(by_name["beta-app"].lifecycle, "beta")

    def test_filter_by_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_lifecycle_roles(roles_dir)

            buf = io.StringIO()
            with (
                mock.patch(
                    "cli.meta.roles.applications.complexity.cli.PROJECT_ROOT",
                    Path(td),
                ),
                redirect_stdout(buf),
            ):
                rc = main(["--format", "string", "--filter", "lifecycle == alpha"])

            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().split(), ["alpha-app"])


class TestParseSortSpec(unittest.TestCase):
    def test_single_column_defaults_to_ascending(self) -> None:
        self.assertEqual(parse_sort_spec("embeds"), [("embeds", False)])

    def test_direction_before_or_after_column(self) -> None:
        self.assertEqual(parse_sort_spec("desc embeds"), [("embeds", True)])
        self.assertEqual(parse_sort_spec("embeds desc"), [("embeds", True)])

    def test_multiple_clauses_keep_order(self) -> None:
        self.assertEqual(
            parse_sort_spec("desc embeds, asc weight"),
            [("embeds", True), ("weight", False)],
        )

    def test_unknown_token_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_sort_spec("desc bogus")

    def test_clause_without_column_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_sort_spec("desc")


class TestMultiKeySort(unittest.TestCase):
    def _build_tie_roles(self, roles_dir: Path) -> None:
        for name in ("a", "b", "c"):
            _mk_role(
                roles_dir,
                name,
                f"{name}:\n  enabled: true\n  shared: true\n",
            )

    def test_later_column_breaks_ties_of_earlier(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_tie_roles(roles_dir)

            buf = io.StringIO()
            with (
                mock.patch(
                    "cli.meta.roles.applications.complexity.cli.PROJECT_ROOT",
                    Path(td),
                ),
                redirect_stdout(buf),
            ):
                rc = main(["--format", "string", "--sort", "desc embeds, desc name"])

            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().split(), ["c", "b", "a"])


class TestSortByCoveredBy(unittest.TestCase):
    def _build_cover_chain(self, roles_dir: Path) -> None:
        _mk_role(
            roles_dir,
            "r1",
            "r1:\n  enabled: true\n  shared: true\n",
        )
        _mk_role(
            roles_dir,
            "r2",
            (
                "r2:\n  enabled: true\n  shared: true\n"
                "r1:\n  enabled: true\n  shared: true\n"
            ),
        )

    def test_covered_by_is_accepted_as_a_sort_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_cover_chain(roles_dir)

            buf = io.StringIO()
            with (
                mock.patch(
                    "cli.meta.roles.applications.complexity.cli.PROJECT_ROOT",
                    Path(td),
                ),
                redirect_stdout(buf),
            ):
                rc = main(
                    ["--format", "string", "--sort", "desc embeds, asc covered_by"]
                )

            self.assertEqual(rc, 0)


class TestVariantMode(unittest.TestCase):
    def _build_variant_roles(self, roles_dir: Path) -> None:
        _mk_role(
            roles_dir,
            "r1",
            "r1:\n  enabled: true\n  shared: true\n",
        )
        _mk_role(
            roles_dir,
            "r2",
            (
                "r2:\n  enabled: true\n  shared: true\n"
                "r1:\n  enabled: true\n  shared: true\n"
            ),
        )
        _mk_variants(
            roles_dir,
            "r2",
            ("- {}\n- services:\n    r1:\n      enabled: false\n      shared: false\n"),
        )

    def _build_many_variant_role(
        self, roles_dir: Path, name: str, *, variants: int
    ) -> None:
        _mk_role(
            roles_dir,
            name,
            f"{name}:\n  enabled: true\n  shared: true\n",
        )
        _mk_variants(roles_dir, name, "- {}\n" * variants)

    def test_variant_recomputes_embeds_per_variant(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_variant_roles(roles_dir)

            rows = compute_variant_complexity_rows(roles_dir)
            r2 = {row.variant: row for row in rows if row.name == "r2"}

            self.assertEqual(set(r2), {0, 1})
            self.assertEqual(r2[0].embeds, 1)
            self.assertEqual(r2[1].embeds, 0)

    def test_variants_count_per_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_variant_roles(roles_dir)

            whole_role_rows = {r.name: r for r in compute_complexity_rows(roles_dir)}
            self.assertEqual(whole_role_rows["r2"].variants, 2)
            self.assertEqual(whole_role_rows["r1"].variants, 1)

            variant_rows = compute_variant_complexity_rows(roles_dir)
            self.assertTrue(all(r.variants == 1 for r in variant_rows))

    def test_bundles_whole_role_uses_compose_packing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_many_variant_role(roles_dir, "big", variants=4)

            whole_role = {r.name: r for r in compute_complexity_rows(roles_dir)}
            self.assertEqual(whole_role["big"].bundles, 2)

    def test_bundles_is_one_per_variant_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_many_variant_role(roles_dir, "big", variants=4)

            variant_rows = compute_variant_complexity_rows(roles_dir)
            self.assertTrue(all(r.bundles == 1 for r in variant_rows))
            self.assertEqual(len([r for r in variant_rows if r.name == "big"]), 4)

    def test_variant_string_output_suffixes_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_variant_roles(roles_dir)

            buf = io.StringIO()
            with (
                mock.patch(
                    "cli.meta.roles.applications.complexity.cli.PROJECT_ROOT",
                    Path(td),
                ),
                redirect_stdout(buf),
            ):
                rc = main(
                    [
                        "--variant",
                        "--format",
                        "string",
                        "--sort",
                        "asc name, asc variant",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().split(), ["r1#0", "r2#0", "r2#1"])

    def test_yaml_format_carries_variant_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            self._build_variant_roles(roles_dir)

            buf = io.StringIO()
            with (
                mock.patch(
                    "cli.meta.roles.applications.complexity.cli.PROJECT_ROOT",
                    Path(td),
                ),
                redirect_stdout(buf),
            ):
                rc = main(["--variant", "--format", "yaml"])

            self.assertEqual(rc, 0)
            data = load_yaml_str(buf.getvalue())
            self.assertTrue(
                all(
                    "id" in row and "variant" in row and "covered_by" in row
                    for row in data
                )
            )
            self.assertTrue(all(isinstance(row["id"], int) for row in data))
            self.assertEqual(
                sorted(row["id"] for row in data), list(range(1, len(data) + 1))
            )
            self.assertEqual(
                [row["row"] for row in data], list(range(1, len(data) + 1))
            )


def _row(
    name: str,
    services: list[str],
    dna: str | None = None,
    variant: int | None = None,
) -> ComplexityRow:
    return ComplexityRow(
        name=name,
        embeds=len(services),
        services=list(services),
        consumers=0,
        consumed_by=[],
        embeds_direct=len(services),
        services_direct=list(services),
        consumers_direct=0,
        consumed_by_direct=[],
        weight=len(services),
        dna=dna or name,
        siblings=[],
        variant=variant,
    )


class TestCoveredBy(unittest.TestCase):
    def test_id_is_numeric_sort_position(self) -> None:
        marked = _mark_covered([_row("A", []), _row("B", [])])
        self.assertEqual([m.id for m in marked], [1, 2])

    def test_green_rows_get_covered_by_zero(self) -> None:
        marked = _mark_covered([_row("A", ["B"]), _row("C", [])])
        self.assertEqual([m.covered_by for m in marked], [0, 0])

    def test_embedded_row_records_its_embedder_id(self) -> None:
        marked = _mark_covered(
            [
                _row("Z", []),
                _row("A", ["B"]),
                _row("B", []),
            ]
        )
        self.assertEqual([m.covered_by for m in marked], [0, 0, 2])

    def test_superset_of_services_alone_does_not_cover(self) -> None:
        marked = _mark_covered(
            [
                _row("Z", []),
                _row("A", ["X", "Y"]),
                _row("B", ["X"]),
            ]
        )
        self.assertEqual([m.covered_by for m in marked], [0, 0, 0])

    def test_first_green_embedder_wins(self) -> None:
        marked = _mark_covered(
            [
                _row("Z", []),
                _row("A", ["X"]),
                _row("B", ["X"]),
                _row("X", []),
            ]
        )
        self.assertEqual([m.covered_by for m in marked], [0, 0, 0, 2])

    def test_variant_gt0_is_never_covered(self) -> None:
        marked = _mark_covered(
            [
                _row("Z", []),
                _row("A", ["B", "C"]),
                _row("B", [], variant=0),
                _row("C", [], variant=1),
            ]
        )
        self.assertEqual([m.covered_by for m in marked], [0, 0, 2, 0])

    def test_variant_gt0_can_still_cover_other_roles(self) -> None:
        marked = _mark_covered(
            [
                _row("Z", []),
                _row("A", ["B"], variant=2),
                _row("B", [], variant=0),
            ]
        )
        self.assertEqual([m.covered_by for m in marked], [0, 0, 2])


if __name__ == "__main__":
    unittest.main()
