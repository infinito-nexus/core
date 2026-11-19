"""Unit tests for :mod:`utils.env.handlers.infinito.cache.stack`."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import apply_custom_env
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache import artefact_base
from utils.env.handlers.infinito.cache import stack as handler
from utils.env.handlers.infinito.package_cache import url as package_url
from utils.env.parser import CUSTOM_ENV

_BLANK = {"CI": "", handler.KEY: ""}
UPSTREAM = "https:/"
CACHE_IP = "172.30.0.4"


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


@patch.dict(
    os.environ, {**_BLANK, artefact_base.KEY: "", package_url.KEY: ""}, clear=False
)
class TestCacheStackCustomEnv(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        (self.repo / CUSTOM_ENV).write_text(f"{handler.KEY}=false\n", encoding="utf-8")
        self.ctx = BuildContext(
            static={artefact_base.KEY: UPSTREAM},
            static_comments={},
            repo_root=self.repo,
            on_gha=False,
            on_act=False,
        )

    def test_a_custom_env_switch_wins_over_the_derived_default(self) -> None:
        eb = EnvBuilder()
        handler.apply(eb, self.ctx)
        self.assertEqual(eb.values[handler.KEY], "false")

    def test_the_artefact_base_and_the_package_url_follow_it(self) -> None:
        eb = EnvBuilder()
        eb.set(artefact_base.FRONTEND_IP_KEY, CACHE_IP)
        eb.set(package_url.IP_KEY, CACHE_IP)
        eb.set(package_url.PORT_KEY, "8081")
        for module in (handler, artefact_base, package_url):
            module.apply(eb, self.ctx)
        apply_custom_env(eb, self.repo)
        self.assertEqual(
            (eb.values[artefact_base.KEY], eb.values[package_url.KEY]),
            (UPSTREAM, ""),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
