"""Unit tests for utils.github.run_name: the emoji head each input's segment
opens with, the openings that terminate a value, and the round trip through
the declared run name."""

from __future__ import annotations

import unittest

from tests.utils.ci.run_name import render
from utils.github import run_name

TPL = (
    "🕹️ "
    "${{ inputs.sequencing != 'auto'"
    " && format('🐛{0} ', inputs.sequencing == 'serial' && '序' || '并') || '' }}"
    "${{ inputs.mode_fail_fast && '🛑 ' || '' }}"
    "${{ inputs.workspace != 'auto'"
    " && format('🧑{0} ', inputs.workspace == 'true' && '是' || '否') || '' }}"
    "${{ inputs.distros != '' && format('🐧{0} ', inputs.distros) || '' }}"
    "${{ inputs.priority != '' && format('⭐{0} ', inputs.priority) || '' }}"
    "${{ inputs.whitelist != ''"
    " && format('🎯{0}', inputs.whitelist) || '🔀 diff (origin/main)' }}"
)


class SegmentTests(unittest.TestCase):
    def test_value_segments_map_their_input_to_a_head(self) -> None:
        self.assertEqual(
            run_name.heads(TPL),
            {
                "sequencing": "🐛",
                "workspace": "🧑",
                "distros": "🐧",
                "priority": "⭐",
                "whitelist": "🎯",
            },
        )

    def test_a_valueless_segment_is_a_marker(self) -> None:
        self.assertEqual(run_name.markers(TPL), {"mode_fail_fast": "🛑"})

    def test_an_input_without_a_value_segment_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            run_name.value_from_title("🕹️ 🐧arch", "lifecycles", TPL)


class OpeningTests(unittest.TestCase):
    def test_compared_operands_and_value_glyphs_are_not_openings(self) -> None:
        found = run_name.openings(TPL)
        self.assertNotIn("auto", found)
        self.assertNotIn("true", found)
        self.assertNotIn("是", found)
        self.assertNotIn("否", found)
        self.assertNotIn("序", found)

    def test_the_diff_fallback_is_an_opening(self) -> None:
        self.assertIn("🔀 diff (origin/main)", run_name.openings(TPL))


class ValueTests(unittest.TestCase):
    def test_a_following_segment_ends_the_value(self) -> None:
        title = "🕹️ 🐧debian ubuntu ⭐web-app-x 🎯__ALL__"
        self.assertEqual(
            run_name.value_from_title(title, "distros", TPL), "debian ubuntu"
        )

    def test_the_diff_fallback_ends_the_value(self) -> None:
        title = "🕹️ 🐧arch 🔀 diff (origin/main)"
        self.assertEqual(run_name.value_from_title(title, "distros", TPL), "arch")

    def test_a_glyph_reads_back_as_its_value(self) -> None:
        title = "🕹️ 🧑是 🐧arch"
        self.assertEqual(run_name.value_from_title(title, "workspace", TPL), "true")

    def test_a_marker_reads_back_by_its_presence(self) -> None:
        self.assertEqual(
            run_name.values_from_title("🕹️ 🛑 🐧arch", TPL)["mode_fail_fast"], "true"
        )
        self.assertEqual(
            run_name.values_from_title("🕹️ 🐧arch", TPL)["mode_fail_fast"], "false"
        )

    def test_a_default_input_records_nothing(self) -> None:
        title = "🕹️ 🐧arch 🔀 diff (origin/main)"
        self.assertEqual(run_name.value_from_title(title, "sequencing", TPL), "")

    def test_a_foreign_title_yields_nothing(self) -> None:
        self.assertEqual(run_name.values_from_title("CI: Pull Request", TPL), {})


class DeclaredTemplateTests(unittest.TestCase):
    def test_the_declared_run_name_round_trips(self) -> None:
        dispatched = {
            "sequencing": "serial",
            "mode_fail_fast": "true",
            "workspace": "true",
            "instructions": "false",
            "filesystem": "ext4",
            "distros": "debian arch",
            "lifecycles": "stable",
            "modes": "swarm compose",
        }
        self.assertEqual(run_name.values_from_title(render(dispatched)), dispatched)


if __name__ == "__main__":
    unittest.main()
