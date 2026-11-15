from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache.paths import base
from utils.env.handlers.infinito.tools import idle as handler
from utils.inventory.tools_idle import GRACE_KEY, STAMP_DIR_KEY, grace_seconds

_BLANK = {GRACE_KEY: "", STAMP_DIR_KEY: ""}


def _apply() -> EnvBuilder:
    eb = EnvBuilder()
    handler.apply(
        eb,
        BuildContext(
            static={},
            static_comments={},
            repo_root=Path("/repo"),
            on_gha=False,
            on_act=False,
        ),
    )
    return eb


class TestToolsIdleDefaults(unittest.TestCase):
    @patch.dict(os.environ, _BLANK, clear=False)
    def test_the_grace_defaults_to_two_hours(self) -> None:
        self.assertEqual(grace_seconds(_apply().values[GRACE_KEY]), 2 * 3600)

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_the_stamps_live_below_the_machine_cache_base(self) -> None:
        stamps = Path(_apply().values[STAMP_DIR_KEY])
        self.assertEqual(stamps.parent, base())


class TestToolsIdleOverride(unittest.TestCase):
    @patch.dict(
        os.environ, {GRACE_KEY: "30m", STAMP_DIR_KEY: "/srv/stamps"}, clear=False
    )
    def test_an_exported_value_wins_over_the_default(self) -> None:
        values = _apply().values
        self.assertEqual(
            (values[GRACE_KEY], values[STAMP_DIR_KEY]), ("30m", "/srv/stamps")
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
