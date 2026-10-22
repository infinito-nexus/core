from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito import ghcr_mirror as handler

_BLANK = {handler.KEY: ""}


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


class TestGhcrMirrorDefault(unittest.TestCase):
    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_developer_machine_pulls_upstream(self) -> None:
        self.assertEqual(_apply(_ctx()), "false")

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_github_runner_uses_the_mirror(self) -> None:
        self.assertEqual(_apply(_ctx(on_gha=True)), "true")

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_act_pulls_upstream(self) -> None:
        self.assertEqual(_apply(_ctx(on_act=True)), "false")


class TestGhcrMirrorIsNotPinnable(unittest.TestCase):
    @patch.dict(os.environ, {handler.KEY: "true"}, clear=False)
    def test_a_live_declaration_is_recomputed_not_adopted(self) -> None:
        self.assertEqual(_apply(_ctx()), "false")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
