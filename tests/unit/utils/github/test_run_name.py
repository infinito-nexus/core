"""Unit tests for utils.github.run_name: the literal frame around a bare
input interpolation, and the dynamic terminator used when no non-whitespace
literal follows the value - the openings of later template segments then end
it instead."""

from __future__ import annotations

import unittest

from utils.github import run_name

EMOJI_TPL = (
    "🕹️ 🐧 ${{ inputs.distros }} "
    "${{ inputs.priority != '' && format('⭐ {0} ', inputs.priority) || '' }}"
    "${{ inputs.whitelist != '' && format('🎯 {0}', inputs.whitelist)"
    " || '🔀 diff (origin/main)' }}"
)

LITERAL_TPL = "Manual CI triggered: ${{ inputs.distros }}; ${{ inputs.whitelist }}"


class DynamicTerminatorTests(unittest.TestCase):
    def test_priority_segment_ends_the_distros(self) -> None:
        title = "🕹️ 🐧 debian ubuntu centos ⭐ web-app-x 🔀 diff (origin/main)"
        self.assertEqual(
            run_name.value_from_title(title, "distros", EMOJI_TPL),
            "debian ubuntu centos",
        )

    def test_whitelist_segment_ends_the_distros(self) -> None:
        title = "🕹️ 🐧 fedora 🎯 web-svc-css"
        self.assertEqual(
            run_name.value_from_title(title, "distros", EMOJI_TPL), "fedora"
        )

    def test_diff_fallback_ends_the_distros(self) -> None:
        title = "🕹️ 🐧 arch 🔀 diff (origin/main)"
        self.assertEqual(run_name.value_from_title(title, "distros", EMOJI_TPL), "arch")

    def test_a_foreign_title_yields_nothing(self) -> None:
        self.assertEqual(
            run_name.value_from_title("CI: Pull Request", "distros", EMOJI_TPL), ""
        )

    def test_without_any_later_opening_the_rest_is_the_value(self) -> None:
        title = "🕹️ 🐧 debian ubuntu"
        self.assertEqual(
            run_name.value_from_title(title, "distros", EMOJI_TPL),
            "debian ubuntu",
        )


class LiteralFrameTests(unittest.TestCase):
    def test_a_non_whitespace_literal_still_splits_exactly(self) -> None:
        title = "Manual CI triggered: debian arch; web-app-x"
        self.assertEqual(
            run_name.value_from_title(title, "distros", LITERAL_TPL), "debian arch"
        )

    def test_the_declared_template_round_trips(self) -> None:
        title = run_name.title_with("distros", "debian arch centos")
        self.assertEqual(
            run_name.value_from_title(title, "distros"), "debian arch centos"
        )
