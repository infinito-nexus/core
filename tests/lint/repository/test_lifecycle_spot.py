"""Lint: ``meta/lifecycle.yml`` is a valid, self-consistent lifecycle SPOT."""

from __future__ import annotations

import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles import lifecycle
from utils.yaml_bootstrap import load_block

from . import PROJECT_ROOT


def _text() -> str:
    return read_text(str(lifecycle.lifecycle_file(PROJECT_ROOT)))


class TestLifecycleSpot(unittest.TestCase):
    def test_the_file_parses_without_errors(self) -> None:
        _, errors = lifecycle.parse(load_block(_text()))
        self.assertEqual(
            errors,
            [],
            f"{lifecycle.FILE_META_LIFECYCLE} breaks its declared shape:\n  "
            + "\n  ".join(errors),
        )

    def test_the_bootstrap_reader_and_pyyaml_agree(self) -> None:
        self.assertEqual(
            load_block(_text()),
            load_yaml_str(_text()),
            f"{lifecycle.FILE_META_LIFECYCLE} must stay inside the block subset "
            "utils.yaml_bootstrap reads, or the env handler sees another file "
            "than every other consumer.",
        )

    def test_no_context_deploys_a_retired_status(self) -> None:
        spot = lifecycle.load()
        leaked = sorted(spot.with_flag(lifecycle.RETIRED) & spot.deployed())
        self.assertEqual(
            leaked,
            [],
            f"A retired status carries {lifecycle.CI_DEPLOY}: the eol rules "
            "exist because no CI round binds such a role. Drop the contexts "
            f"from: {', '.join(leaked)}",
        )

    def test_every_status_is_described_once_and_ordered_once(self) -> None:
        spot = lifecycle.load()
        self.assertEqual(sorted(spot.order), sorted(spot.statuses))
        self.assertEqual(len(set(spot.order)), len(spot.order))


if __name__ == "__main__":
    unittest.main()
