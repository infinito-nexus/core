"""Unit tests for :mod:`utils.env.handlers.infinito.cache.host_pacman_path`."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache import host_pacman_path as handler

HELPER = "utils.env.handlers.infinito.cache.host_pacman_path.run_helper"
ARCH = 'NAME="Arch Linux"\nID=arch\n'
MANJARO = 'NAME="Manjaro Linux"\nID=manjaro\nID_LIKE=arch\n'
ENDEAVOUR = 'NAME="EndeavourOS"\nID="endeavouros"\nID_LIKE="arch"\n'


@patch.dict(os.environ, {handler.KEY: ""}, clear=False)
class TestHostPacmanPath(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cache = self.tmp / "pkg"
        self.cache.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _apply(self, os_release: str | None, distro: str, conf_output: str) -> str:
        path = self.tmp / "os-release"
        if os_release is not None:
            path.write_text(os_release)
        eb = EnvBuilder()
        eb.set("INFINITO_DISTRO", distro)
        ctx = BuildContext(
            static={},
            static_comments={},
            repo_root=Path("/repo"),
            on_gha=False,
            on_act=False,
        )
        with (
            patch.object(handler, "OS_RELEASE", path),
            patch(HELPER, return_value=conf_output),
        ):
            handler.apply(eb, ctx)
        return eb.values[handler.KEY]

    def test_an_arch_host_offers_its_first_cache_dir_to_an_arch_stack(self) -> None:
        self.assertEqual(
            self._apply(ARCH, "arch", f"{self.cache}/\n/var/cache/other/\n"),
            str(self.cache),
        )

    def test_a_manjaro_host_offers_nothing(self) -> None:
        self.assertEqual(self._apply(MANJARO, "arch", f"{self.cache}/\n"), "")

    def test_an_arch_derivative_offers_nothing(self) -> None:
        self.assertEqual(self._apply(ENDEAVOUR, "arch", f"{self.cache}/\n"), "")

    def test_a_host_without_os_release_offers_nothing(self) -> None:
        self.assertEqual(self._apply(None, "arch", f"{self.cache}/\n"), "")

    def test_a_stack_without_pacman_gets_nothing(self) -> None:
        self.assertEqual(self._apply(ARCH, "debian", f"{self.cache}/\n"), "")

    def test_an_arch_host_without_pacman_conf_offers_nothing(self) -> None:
        self.assertEqual(self._apply(ARCH, "arch", ""), "")

    def test_a_cache_dir_that_does_not_exist_is_not_offered(self) -> None:
        self.assertEqual(self._apply(ARCH, "arch", f"{self.cache}/missing/\n"), "")

    def test_an_exported_path_wins(self) -> None:
        with patch.dict(os.environ, {handler.KEY: "/elsewhere"}, clear=False):
            self.assertEqual(
                self._apply(MANJARO, "arch", f"{self.cache}/\n"), "/elsewhere"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
