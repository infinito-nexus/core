"""Unit tests for :mod:`utils.env.handlers.infinito_variant_time_overflow`."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers import infinito_variant_time_overflow as handler


def _ctx(*, on_gha: bool) -> BuildContext:
    return BuildContext(
        static={},
        static_comments={},
        repo_root=Path("/repo"),
        on_gha=on_gha,
        on_act=False,
    )


class TestApply(unittest.TestCase):
    def test_defaults_to_cut(self) -> None:
        for on_gha in (True, False):
            with patch.dict("os.environ", {}, clear=True):
                eb = EnvBuilder()
                handler.apply(eb, _ctx(on_gha=on_gha))
            self.assertEqual(eb.values[handler.KEY], "cut")
            self.assertEqual(eb.comments[handler.KEY], handler.COMMENT)

    def test_caller_env_wins_over_default(self) -> None:
        with patch.dict("os.environ", {handler.KEY: "fail"}, clear=True):
            eb = EnvBuilder()
            handler.apply(eb, _ctx(on_gha=True))
        self.assertEqual(eb.values[handler.KEY], "fail")


if __name__ == "__main__":
    unittest.main()
