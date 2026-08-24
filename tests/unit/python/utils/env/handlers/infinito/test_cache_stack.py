"""Unit tests for :mod:`utils.env.handlers.infinito.cache_stack`."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito import cache_stack as handler

_BLANK = {"CI": "", handler.KEY: ""}


def _ctx(*, on_gha: bool = False, on_act: bool = False) -> BuildContext:
    return BuildContext(
        static={},
        static_comments={handler.KEY: handler.COMMENT},
        repo_root=Path("/repo"),
        on_gha=on_gha,
        on_act=on_act,
    )


def _apply(ctx: BuildContext) -> str:
    eb = EnvBuilder()
    handler.apply(eb, ctx)
    return eb.values[handler.KEY]


class TestCacheStackDefault(unittest.TestCase):
    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_developer_machine_runs_the_stack(self) -> None:
        self.assertEqual(_apply(_ctx()), "true")

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_github_runner_does_not(self) -> None:
        self.assertEqual(_apply(_ctx(on_gha=True)), "false")

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_act_does_not(self) -> None:
        self.assertEqual(_apply(_ctx(on_act=True)), "false")

    @patch.dict(os.environ, {**_BLANK, "CI": "true"}, clear=False)
    def test_a_generic_ci_signal_does_not(self) -> None:
        self.assertEqual(_apply(_ctx()), "false")


class TestCacheStackIsNotPinnable(unittest.TestCase):
    @patch.dict(os.environ, {**_BLANK, handler.KEY: "false"}, clear=False)
    def test_a_live_declaration_is_recomputed_not_adopted(self) -> None:
        self.assertEqual(_apply(_ctx()), "true")

    @patch.dict(os.environ, {**_BLANK, handler.KEY: "true"}, clear=False)
    def test_the_same_holds_in_the_other_direction(self) -> None:
        self.assertEqual(_apply(_ctx(on_gha=True)), "false")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
