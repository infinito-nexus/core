"""Unit tests for :mod:`utils.env.handlers.infinito_max_runtime`."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers import infinito_max_runtime as handler


def _ctx(*, on_gha: bool) -> BuildContext:
    return BuildContext(
        static={},
        static_comments={},
        repo_root=Path("/repo"),
        on_gha=on_gha,
        on_act=False,
    )


class TestApply(unittest.TestCase):
    def test_six_hours_on_github(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            handler.apply(eb, _ctx(on_gha=True))
        self.assertEqual(eb.values[handler.KEY], "6h")
        self.assertEqual(eb.comments[handler.KEY], handler.COMMENT)

    def test_forty_eight_hours_off_github(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            eb = EnvBuilder()
            handler.apply(eb, _ctx(on_gha=False))
        self.assertEqual(eb.values[handler.KEY], "48h")

    def test_caller_env_wins_over_default(self) -> None:
        with patch.dict("os.environ", {handler.KEY: "12h"}, clear=True):
            eb = EnvBuilder()
            handler.apply(eb, _ctx(on_gha=True))
        self.assertEqual(eb.values[handler.KEY], "12h")


if __name__ == "__main__":
    unittest.main()
