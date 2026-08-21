from __future__ import annotations

import unittest

from cli.meta.ci import plan
from utils.symbol_glossary import to_emoji


def _entry(
    app: str,
    variant: str,
    mode: str,
    *,
    priority: bool = False,
    identifier: str = "0",
    covered: str = "0",
    clone: bool = False,
) -> dict:
    return {
        "apps": app,
        "variant": variant,
        "mode": mode,
        "tor": "true" if variant == "0" else "false",
        "disable": "",
        "priority": "true" if priority else "false",
        "weight": "42",
        "id": identifier,
        "covered": covered,
        "clone": "true" if clone else "false",
        "distro": "debian",
        "filesystem": "zfs",
        "label": f"{to_emoji(mode)}{app} {variant}",
    }


_PRIORITY = [_entry("web-app-a", "0", "compose", priority=True, identifier="3")]
_REGULAR = [
    _entry("web-app-b", "0", "swarm", identifier="5"),
    _entry("web-app-b", "1", "compose", identifier="9"),
]
_CUT = [_entry("web-app-c", "0", "compose", identifier="11", covered="5")]
_ENTRIES = _PRIORITY + _REGULAR + _CUT


class TestCells(unittest.TestCase):
    def test_a_row_in_a_chunk_reports_that_chunk(self) -> None:
        rows = plan.cells(_ENTRIES, [_PRIORITY, _REGULAR])
        chunk = plan._COLUMNS.index("chunk")
        self.assertEqual([row[chunk] for row in rows], ["0", "1", "1", ""])

    def test_a_priority_row_is_starred_not_ticked(self) -> None:
        rows = plan.cells(_ENTRIES, [_PRIORITY, _REGULAR])
        status = plan._COLUMNS.index("triggered")
        self.assertEqual(rows[0][status], to_emoji("priority"))
        self.assertEqual(rows[1][status], to_emoji("enabled"))

    def test_a_row_outside_the_sweep_is_marked_disabled(self) -> None:
        rows = plan.cells(_ENTRIES, [_PRIORITY])
        self.assertEqual(
            rows[1][plan._COLUMNS.index("triggered")], to_emoji("disabled")
        )
        self.assertEqual(rows[1][plan._COLUMNS.index("chunk")], "")

    def test_a_clone_is_named_in_its_own_column(self) -> None:
        entries = [*_ENTRIES, _entry("web-app-d", "0", "compose", clone=True)]
        rows = plan.cells(entries, [_PRIORITY, _REGULAR])
        clone = plan._COLUMNS.index("clone")
        self.assertEqual(rows[0][clone], "")
        self.assertEqual(rows[-1][clone], to_emoji("clone"))

    def test_the_mode_is_rendered_as_its_glyph(self) -> None:
        rows = plan.cells(_ENTRIES, [_PRIORITY, _REGULAR])
        mode = plan._COLUMNS.index("mode")
        self.assertEqual(rows[0][mode], to_emoji("compose"))
        self.assertEqual(rows[1][mode], to_emoji("swarm"))

    def test_a_covered_row_names_the_row_number_that_covers_it(self) -> None:
        covered = plan._COLUMNS.index("covered_by")
        rows = plan.cells(_ENTRIES, [_PRIORITY, _REGULAR])
        self.assertEqual(rows[0][covered], "")
        self.assertEqual(rows[3][covered], "2")

    def test_a_covered_row_is_cut_instead_of_deployed(self) -> None:
        rows = plan.cells(_ENTRIES, [_PRIORITY, _REGULAR])
        self.assertEqual(
            rows[3][plan._COLUMNS.index("triggered")], to_emoji("redundant")
        )
        self.assertEqual(rows[3][plan._COLUMNS.index("chunk")], "")

    def test_a_clone_is_cut_as_well(self) -> None:
        entries = [*_ENTRIES, _entry("web-app-d", "0", "compose", clone=True)]
        rows = plan.cells(entries, [_PRIORITY, _REGULAR])
        self.assertEqual(
            rows[-1][plan._COLUMNS.index("triggered")], to_emoji("redundant")
        )

    def test_a_pinned_clone_stays_in_the_run(self) -> None:
        entries = [_entry("web-app-d", "0", "compose", priority=True, clone=True)]
        rows = plan.cells(entries, [entries])
        self.assertEqual(
            rows[0][plan._COLUMNS.index("triggered")], to_emoji("priority")
        )

    def test_the_id_counts_the_rows_even_when_discovery_ids_repeat(self) -> None:
        identifier = plan._COLUMNS.index("id")
        entries = [*_ENTRIES, _entry("web-app-a", "0", "swarm", identifier="3")]
        rows = plan.cells(entries, [_PRIORITY, _REGULAR])
        self.assertEqual([row[identifier] for row in rows], ["1", "2", "3", "4", "5"])

    def test_the_tor_state_is_rendered_as_its_glyph(self) -> None:
        rows = plan.cells(_ENTRIES, [_PRIORITY, _REGULAR])
        tor = plan._COLUMNS.index("tor")
        self.assertEqual(rows[0][tor], to_emoji("tor"))
        self.assertEqual(rows[2][tor], to_emoji("clearnet"))

    def test_every_row_carries_its_own_distro_and_filesystem_glyph(self) -> None:
        rows = plan.cells(_ENTRIES, [_PRIORITY, _REGULAR])
        distro = plan._COLUMNS.index("distro")
        filesystem = plan._COLUMNS.index("filesystem")
        self.assertTrue(all(row[distro] == to_emoji("debian") for row in rows))
        self.assertTrue(all(row[filesystem] == to_emoji("zfs") for row in rows))


class TestRender(unittest.TestCase):
    def _rows(self) -> list[tuple[str, ...]]:
        return plan.cells(_ENTRIES, [_PRIORITY, _REGULAR])

    def test_markdown_is_one_table_with_a_chunk_column(self) -> None:
        out = plan.render_markdown("sweep 0", self._rows())
        self.assertEqual(out.count("| ---"), 0)
        self.assertEqual(out.count("\n|---"), 1)
        self.assertIn(f"{to_emoji('chunk')} Chunk", out)
        self.assertIn("web-app-a", out)

    def test_markdown_keeps_one_line_per_row(self) -> None:
        out = plan.render_markdown("sweep 0", self._rows())
        body = [line for line in out.splitlines() if line.startswith("| web")]
        self.assertEqual(len(body), 0)
        self.assertEqual(len([ln for ln in out.splitlines() if ln.startswith("| ")]), 5)

    def test_cli_pads_to_display_width(self) -> None:
        out = plan.render_cli("sweep 0", self._rows())
        lines = out.splitlines()
        self.assertEqual(lines[0], "sweep 0")
        self.assertTrue(lines[2].startswith("---"))
        self.assertEqual(len(lines), 3 + len(_ENTRIES))


if __name__ == "__main__":
    unittest.main()
