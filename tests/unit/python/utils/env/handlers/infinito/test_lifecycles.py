from __future__ import annotations

import functools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito import lifecycles as handler
from utils.roles import lifecycle

_UPSTREAM_MAIN = {
    "GITHUB_REPOSITORY": "infinito-nexus/core",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_EVENT_NAME": "push",
}
_BRANCH_SET = "alpha beta rc stable deprecated"
_MAIN_SET = "beta rc stable"


def _apply(env: dict[str, str], *, on_gha: bool) -> EnvBuilder:
    eb = EnvBuilder()
    with patch.dict("os.environ", env, clear=True):
        handler.apply(
            eb,
            BuildContext(
                static={},
                static_comments={},
                repo_root=Path("/repo"),
                on_gha=on_gha,
                on_act=False,
            ),
        )
    return eb


class TestApply(unittest.TestCase):
    def test_a_local_run_gets_the_branch_set(self) -> None:
        eb = _apply({}, on_gha=False)
        self.assertEqual(_BRANCH_SET, eb.values[handler.KEY])
        self.assertIn(lifecycle.FILE_META_LIFECYCLE, eb.comments[handler.KEY])

    def test_an_upstream_main_push_gets_the_main_set(self) -> None:
        self.assertEqual(
            _MAIN_SET, _apply(_UPSTREAM_MAIN, on_gha=True).values[handler.KEY]
        )

    def test_the_same_variables_off_github_get_the_branch_set(self) -> None:
        eb = _apply(_UPSTREAM_MAIN, on_gha=False)
        self.assertEqual(_BRANCH_SET, eb.values[handler.KEY])

    def test_a_fork_main_gets_the_branch_set(self) -> None:
        env = {**_UPSTREAM_MAIN, "GITHUB_REPOSITORY": "someone/core"}
        self.assertEqual(_BRANCH_SET, _apply(env, on_gha=True).values[handler.KEY])

    def test_a_pull_request_gets_the_branch_set(self) -> None:
        env = {
            **_UPSTREAM_MAIN,
            "GITHUB_REF": "refs/pull/1/merge",
            "GITHUB_EVENT_NAME": "pull_request",
        }
        self.assertEqual(_BRANCH_SET, _apply(env, on_gha=True).values[handler.KEY])

    def test_an_explicit_caller_value_wins(self) -> None:
        env = {**_UPSTREAM_MAIN, handler.KEY: "eol"}
        self.assertEqual("eol", _apply(env, on_gha=True).values[handler.KEY])

    def test_the_value_follows_the_ci_deploy_lists_in_the_spot(self) -> None:
        text = read_text(str(lifecycle.lifecycle_file(PROJECT_ROOT)))
        block = "      - rc\n    flags:\n      - production\n    ci-deploy:\n"
        marker = f"{block}      - upstream-main\n"
        self.assertIn(marker, text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = lifecycle.lifecycle_file(root)
            target.parent.mkdir(parents=True)
            target.write_text(text.replace(marker, block), encoding="utf-8")
            fixture = functools.partial(lifecycle.default_envelope, root=root)
            with patch.object(handler, "default_envelope", fixture):
                eb = _apply(_UPSTREAM_MAIN, on_gha=True)
        self.assertEqual("beta rc", eb.values[handler.KEY])


if __name__ == "__main__":
    unittest.main()
