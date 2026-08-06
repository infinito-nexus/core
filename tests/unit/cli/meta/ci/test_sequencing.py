from __future__ import annotations

import unittest
from unittest import mock

from cli.meta.ci import sequencing

_SELECTIONS = {
    "swarm": ["a#0", "a#1", "b#0"],
    "compose": ["a", "b"],
    "host": ["c"],
}


def _patched(modes: str) -> int:
    with (
        mock.patch.object(sequencing, "discover", lambda mode, **_: _SELECTIONS[mode]),
        mock.patch.object(sequencing, "get_variants", dict),
        mock.patch.object(
            sequencing,
            "compose_bundle_counts",
            lambda apps, _variants: dict.fromkeys(apps, 2),
        ),
    ):
        return sequencing.line_jobs(modes, whitelist="", blacklist="", lifecycles="")


class TestLineJobs(unittest.TestCase):
    def test_swarm_tokens_map_one_to_one_and_roles_bundle(self) -> None:
        self.assertEqual(_patched("swarm compose host"), 3 + 4 + 2)

    def test_inactive_modes_do_not_count(self) -> None:
        self.assertEqual(_patched("swarm"), 3)


class TestDecide(unittest.TestCase):
    def test_auto_serialises_above_the_threshold(self) -> None:
        with mock.patch.dict("os.environ", {"INFINITO_CI_SEQUENTIAL_THRESHOLD": "65"}):
            self.assertEqual(sequencing.decide(66, "auto"), "serial")
            self.assertEqual(sequencing.decide(65, "auto"), "parallel")

    def test_a_forced_choice_skips_the_threshold(self) -> None:
        self.assertEqual(sequencing.decide(None, "serial"), "serial")
        self.assertEqual(sequencing.decide(None, "parallel"), "parallel")


if __name__ == "__main__":
    unittest.main()
