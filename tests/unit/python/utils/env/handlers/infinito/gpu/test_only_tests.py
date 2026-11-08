from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder, apply_custom_env
from utils.env.handlers.infinito.gpu import only_tests as handler

_BLANK = {handler.KEY: ""}


def _apply(gpu_count: str) -> EnvBuilder:
    eb = EnvBuilder()
    eb.set(handler.GPU_COUNT_KEY, gpu_count)
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


class TestGpuTestsDefault(unittest.TestCase):
    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_host_that_reserves_a_gpu_runs_them(self) -> None:
        self.assertEqual(_apply("all").values[handler.KEY], "true")

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_host_without_a_gpu_skips_them(self) -> None:
        self.assertEqual(_apply("0").values[handler.KEY], "false")

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_disabled_gpu_skips_them(self) -> None:
        self.assertEqual(_apply("none").values[handler.KEY], "false")


class TestGpuTestsOverride(unittest.TestCase):
    @patch.dict(os.environ, _BLANK, clear=False)
    def test_custom_env_switches_them_off_on_a_gpu_host(self) -> None:
        eb = _apply("all")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "custom.env").write_text(f"{handler.KEY}=false\n")
            apply_custom_env(eb, Path(tmp))
        self.assertEqual(eb.values[handler.KEY], "false")

    @patch.dict(os.environ, {handler.KEY: "false"}, clear=False)
    def test_an_exported_value_wins_over_the_derivation(self) -> None:
        self.assertEqual(_apply("all").values[handler.KEY], "false")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
