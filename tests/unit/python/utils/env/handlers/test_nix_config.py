from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers import nix_config as handler

_TOKENS_LINE = "access-tokens = github.com=placeholder-not-a-token"
_CALLER = {handler.KEY: f"{_TOKENS_LINE}\naccept-flake-config = true\n"}


def _ctx(*, on_gha: bool = False, on_act: bool = False) -> BuildContext:
    return BuildContext(
        static={},
        static_comments={},
        repo_root=Path("/repo"),
        on_gha=on_gha,
        on_act=on_act,
    )


def _apply(ctx: BuildContext) -> dict[str, str]:
    eb = EnvBuilder()
    handler.apply(eb, ctx)
    return eb.values


class TestNixConfigTokenStaysOffTheHost(unittest.TestCase):
    @patch.dict(os.environ, _CALLER, clear=False)
    def test_a_github_runner_keeps_only_the_access_tokens_line(self) -> None:
        self.assertEqual(_apply(_ctx(on_gha=True)), {handler.KEY: _TOKENS_LINE})

    @patch.dict(os.environ, _CALLER, clear=False)
    def test_act_never_writes_the_token(self) -> None:
        self.assertNotIn(handler.KEY, _apply(_ctx(on_act=True)))

    @patch.dict(os.environ, _CALLER, clear=False)
    def test_a_developer_machine_never_writes_the_token(self) -> None:
        self.assertNotIn(handler.KEY, _apply(_ctx()))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
