from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito import distro as handler
from utils.env.parser import CUSTOM_ENV

FALLBACK = "debian"
ARCH = 'NAME="Arch Linux"\nID=arch\n'
DEBIAN = 'NAME="Debian GNU/Linux"\nID=debian\n'
UBUNTU = 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n'
MANJARO = 'NAME="Manjaro Linux"\nID=manjaro\nID_LIKE=arch\n'
FEDORA = 'NAME="Fedora Linux"\nID=fedora\n'


@patch.dict(os.environ, {handler.KEY: ""}, clear=False)
class TestHostDistro(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def _apply(self, os_release: str | None, *, ci: bool = False) -> str:
        path = self.tmp / f"os-release-{len(list(self.tmp.iterdir()))}"
        if os_release is not None:
            path.write_text(os_release, encoding="utf-8")
        eb = EnvBuilder()
        ctx = BuildContext(
            static={handler.KEY: FALLBACK},
            static_comments={},
            repo_root=self.repo,
            on_gha=ci,
            on_act=False,
        )
        with patch.object(handler, "OS_RELEASE", path):
            handler.apply(eb, ctx)
        return eb.values[handler.KEY]

    def test_an_arch_host_deploys_arch(self) -> None:
        self.assertEqual(self._apply(ARCH), "arch")

    def test_a_debian_or_ubuntu_host_deploys_its_own_distro(self) -> None:
        for os_release, expected in ((DEBIAN, "debian"), (UBUNTU, "ubuntu")):
            with self.subTest(expected=expected):
                self.assertEqual(self._apply(os_release), expected)

    def test_any_other_host_keeps_the_fallback(self) -> None:
        for os_release in (MANJARO, FEDORA, None):
            with self.subTest(os_release=os_release):
                self.assertEqual(self._apply(os_release), FALLBACK)

    def test_an_exported_value_wins_over_the_host(self) -> None:
        with patch.dict(os.environ, {handler.KEY: "fedora"}, clear=False):
            self.assertEqual(self._apply(ARCH), "fedora")

    def test_a_custom_env_value_wins_over_the_host_and_the_export(self) -> None:
        (self.repo / CUSTOM_ENV).write_text(f"{handler.KEY}=ubuntu\n", encoding="utf-8")
        with patch.dict(os.environ, {handler.KEY: "fedora"}, clear=False):
            self.assertEqual(self._apply(ARCH), "ubuntu")

    def test_a_ci_runner_keeps_the_fallback(self) -> None:
        self.assertEqual(self._apply(ARCH, ci=True), FALLBACK)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
