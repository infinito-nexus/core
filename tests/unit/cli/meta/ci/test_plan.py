from __future__ import annotations

import unittest

from cli.meta.ci import plan


class TestCells(unittest.TestCase):
    def test_swarm_rows_are_per_variant_tokens_with_variant_weights(self) -> None:
        rows = [
            ("svc-prio#0", "⭐"),
            ("web-app-a#1", "✅"),
            ("svc-prio#1", "⭐"),
            ("web-app-b#0", "❌"),
        ]
        cells = plan._cells(
            "swarm",
            rows,
            {"svc-prio#0": 5, "svc-prio#1": 3, "web-app-a#1": 10, "web-app-b#0": 7},
            {"svc-prio": 2, "web-app-a": 2, "web-app-b": 1},
            priority="svc-prio",
            distros="debian",
        )
        self.assertEqual(
            cells,
            [
                ("1", "svc-prio", "5", "⭐", "0", "debian", "⭐"),
                ("2", "web-app-a", "10", "", "1", "debian", "✅"),
                ("3", "svc-prio", "3", "⭐", "1", "debian", "⭐"),
                ("4", "web-app-b", "7", "", "0", "debian", "❌"),
            ],
        )

    def test_bundled_modes_keep_one_row_per_role(self) -> None:
        rows = [("svc-prio", "⭐"), ("web-app-a", "✅")]
        for mode in ("compose", "host"):
            cells = plan._cells(
                mode,
                rows,
                {"svc-prio": 5, "web-app-a": 10},
                {"svc-prio": 2, "web-app-a": 1},
                priority="svc-prio",
                distros="debian",
            )
            self.assertEqual(
                cells,
                [
                    ("1", "svc-prio", "5", "⭐", "0,1", "debian", "⭐"),
                    ("2", "web-app-a", "10", "", "0", "debian", "✅"),
                ],
                mode,
            )


class TestRender(unittest.TestCase):
    def setUp(self) -> None:
        self.sections = [
            (
                "compose",
                54,
                [
                    ("1", "web-app-a", "10", "", "0", "debian", "✅"),
                    ("2", "web-app-b", "7", "", "0", "debian", "❌"),
                ],
            ),
            ("host", 10, [("1", "svc-x", "3", "", "0", "debian", "✅")]),
        ]

    def test_markdown_has_one_section_per_mode_and_no_legend(self) -> None:
        out = plan.render_markdown(self.sections)
        self.assertIn("### 🐳 compose (max jobs: 54)", out)
        self.assertIn("### 💻 host (max jobs: 10)", out)
        self.assertIn(
            "| 🆔 Id | 📛 Name | 📊 Weight | ⭐ Priority | 🎯 Variant "
            "| 🐧 Distros | ✅ Triggered |",
            out,
        )
        self.assertIn("| 2 | web-app-b | 7 |  | 0 | debian | ❌ |", out)
        self.assertNotIn("priority line", out)

    def test_cli_renders_display_width_aligned_sections(self) -> None:
        out = plan.render_cli(self.sections)
        self.assertIn("🐳 compose (max jobs: 54)", out)
        self.assertIn("💻 host (max jobs: 10)", out)
        header_line = next(
            line for line in out.splitlines() if line.startswith("🆔 Id")
        )
        rule_line = next(line for line in out.splitlines() if line.startswith("---"))
        self.assertEqual(len(rule_line), len(rule_line.rstrip()))
        data_line = next(line for line in out.splitlines() if "web-app-a" in line)
        name_col = rule_line.index("  ", rule_line.index("-")) + 2
        self.assertEqual(data_line[name_col : name_col + 9], "web-app-a")
        self.assertTrue(header_line)


if __name__ == "__main__":
    unittest.main()
