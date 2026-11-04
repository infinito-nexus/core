"""The README replay rides on the variant that declares the guide host.

Which row carries it is read out of ``meta/variants.yml``, not computed, so a
role moves the replay by moving the ``docs`` service between its variants.

Two traps this guards. The row still has to run in the guide's own mode: the
replay is a second deploy on the same runner, and on a swarm row that runner
would have to bring a compose stack up beside a swarm one. And the job title
carries no marker any more, so a wrongly marked row is invisible in the run
list; only these assertions catch it.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from utils.github.variant import instructions


def _entry(app: str, variant: str, mode: str, **overrides: str) -> dict[str, str]:
    entry = {
        "apps": app,
        "variant": variant,
        "mode": mode,
        "priority": "false",
        "clone": "false",
        "covered": "0",
        "instructions": "",
        "label": f"{app}#{variant}",
    }
    entry.update(overrides)
    return entry


_VARIANTS = {
    "web-app-x": [
        {"services": {"a": {"enabled": True}}},
        {"services": {"a": {"enabled": True}, "docs": {"enabled": True}}},
    ]
}


def _mark(entries, mode="compose", variants=None):
    with patch.object(instructions, "guide_deployable", return_value=mode):
        return instructions.mark(
            entries, variants if variants is not None else _VARIANTS
        )


class TestInstructionsMode(unittest.TestCase):
    def test_the_variant_that_declares_the_guide_carries_it(self) -> None:
        marked = _mark([_entry("web-app-x", "1", "compose")])
        self.assertEqual("compose", marked[0]["instructions"])

    def test_a_variant_without_the_guide_carries_nothing(self) -> None:
        marked = _mark([_entry("web-app-x", "0", "compose")])
        self.assertEqual("", marked[0]["instructions"])

    def test_a_swarm_row_never_carries_a_compose_replay(self) -> None:
        marked = _mark([_entry("web-app-x", "1", "swarm")])
        self.assertEqual("", marked[0]["instructions"])

    def test_the_swarm_row_is_skipped_and_the_compose_row_takes_it(self) -> None:
        marked = _mark(
            [_entry("web-app-x", "1", "swarm"), _entry("web-app-x", "1", "compose")]
        )
        self.assertEqual(["", "compose"], [e["instructions"] for e in marked])

    def test_a_host_role_carries_it_on_its_host_row(self) -> None:
        marked = _mark([_entry("web-app-x", "1", "host")], mode="host")
        self.assertEqual("host", marked[0]["instructions"])

    def test_a_redundant_row_carries_nothing(self) -> None:
        marked = _mark([_entry("web-app-x", "1", "compose", covered="7")])
        self.assertEqual("", marked[0]["instructions"])

    def test_only_one_row_per_role_is_marked(self) -> None:
        marked = _mark(
            [_entry("web-app-x", "1", "compose"), _entry("web-app-x", "1", "compose")]
        )
        self.assertEqual(["compose", ""], [e["instructions"] for e in marked])

    def test_an_unknown_variant_index_carries_nothing(self) -> None:
        marked = _mark([_entry("web-app-x", "9", "compose")])
        self.assertEqual("", marked[0]["instructions"])

    def test_the_label_is_left_alone(self) -> None:
        marked = _mark(
            [_entry("web-app-x", "1", "swarm"), _entry("web-app-x", "1", "compose")]
        )
        self.assertEqual(["web-app-x#1", "web-app-x#1"], [e["label"] for e in marked])


if __name__ == "__main__":
    unittest.main()
