from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito import build as handler

_BLANK = {handler.KEY: ""}


def _ctx(*, on_gha: bool = False, on_act: bool = False) -> BuildContext:
    return BuildContext(
        static={},
        static_comments={},
        repo_root=Path("/repo"),
        on_gha=on_gha,
        on_act=on_act,
    )


def _apply(ctx: BuildContext) -> str | None:
    eb = EnvBuilder()
    handler.apply(eb, ctx)
    return eb.values.get(handler.KEY)


class TestBuildDefault(unittest.TestCase):
    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_github_runner_runs_the_published_image(self) -> None:
        self.assertEqual(_apply(_ctx(on_gha=True)), "0")

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_developer_machine_keeps_the_static_value(self) -> None:
        self.assertIsNone(_apply(_ctx()))

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_act_keeps_the_static_value(self) -> None:
        self.assertIsNone(_apply(_ctx(on_act=True)))

    @patch.dict(os.environ, {handler.KEY: "1"}, clear=False)
    def test_a_github_job_that_builds_its_own_image_keeps_building(self) -> None:
        self.assertEqual(_apply(_ctx(on_gha=True)), "1")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
