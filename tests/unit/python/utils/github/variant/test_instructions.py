"""The README replay rides on a row that runs in the guide's own mode.

The replay is a second deploy on the same runner. On a swarm row that runner
would have to bring a compose stack up beside a swarm one, so the marker has to
land on a compose row for a role that ships a stack, and on a host row for one
installed onto the machine.

The trap this guards is quiet: marking the wrong row still produces a 📖 in a
job title, so a run looks like it replayed the instructions either way.
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
        {"services": {"a": {"enabled": True}, "b": {"enabled": True}}},
        {"services": {"a": {"enabled": True}}},
    ]
}


def _mark(entries, mode="compose", variants=None):
    """Mark with the guide's mode forced, leaving the variant search real.

    Both bindings are patched: ``mark`` resolved the name at import, while
    ``guide_variant`` calls its own module's copy.
    """
    with (
        patch.object(instructions, "guide_deployable", return_value=mode),
        patch("utils.roles.guide.guide_deployable", return_value=mode),
    ):
        return instructions.mark(
            entries, variants if variants is not None else _VARIANTS
        )


class TestInstructionsMode(unittest.TestCase):
    def test_the_compose_row_of_the_smallest_variant_carries_it(self) -> None:
        marked = _mark([_entry("web-app-x", "1", "compose")])
        self.assertEqual("compose", marked[0]["instructions"])

    def test_a_swarm_row_never_carries_a_compose_replay(self) -> None:
        marked = _mark([_entry("web-app-x", "1", "swarm")])
        self.assertEqual("", marked[0]["instructions"])

    def test_the_swarm_row_is_skipped_and_the_compose_row_takes_it(self) -> None:
        marked = _mark(
            [_entry("web-app-x", "1", "swarm"), _entry("web-app-x", "1", "compose")]
        )
        self.assertEqual(["", "compose"], [e["instructions"] for e in marked])

    def test_a_variant_deployed_only_in_swarm_does_not_win_the_search(self) -> None:
        marked = _mark(
            [_entry("web-app-x", "1", "swarm"), _entry("web-app-x", "0", "compose")]
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

    def test_the_label_gains_the_glyph_only_where_it_is_marked(self) -> None:
        marked = _mark(
            [_entry("web-app-x", "1", "swarm"), _entry("web-app-x", "1", "compose")]
        )
        self.assertEqual("web-app-x#1", marked[0]["label"])
        self.assertNotEqual("web-app-x#1", marked[1]["label"])


if __name__ == "__main__":
    unittest.main()
