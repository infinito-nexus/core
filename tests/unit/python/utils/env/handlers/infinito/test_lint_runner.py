from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito import lint_runner as handler


def _ctx(*, on_gha: bool, on_act: bool) -> BuildContext:
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


@patch.dict(os.environ, {handler.KEY: ""})
class TestLintRunner(unittest.TestCase):
    def test_a_github_runner_lints_on_the_host(self) -> None:
        self.assertEqual(_apply(_ctx(on_gha=True, on_act=False)), "host")

    def test_act_lints_on_the_host(self) -> None:
        self.assertEqual(_apply(_ctx(on_gha=False, on_act=True)), "host")

    def test_a_developer_machine_keeps_the_static_value(self) -> None:
        self.assertIsNone(_apply(_ctx(on_gha=False, on_act=False)))

    def test_a_github_job_that_sets_the_runner_keeps_it(self) -> None:
        with patch.dict(os.environ, {handler.KEY: "docker"}):
            self.assertEqual(_apply(_ctx(on_gha=True, on_act=False)), "docker")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
