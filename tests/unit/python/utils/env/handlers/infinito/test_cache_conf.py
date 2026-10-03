"""Unit tests for :mod:`utils.env.handlers.infinito.cache.conf`."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache import conf as handler


def _ctx(root: Path) -> BuildContext:
    return BuildContext(
        static={},
        static_comments={handler.KEY: handler.COMMENT},
        repo_root=root,
        on_gha=False,
        on_act=False,
    )


class TestApply(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def test_the_map_is_rendered_in_the_checkout_that_builds_it(self) -> None:
        eb = EnvBuilder()

        handler.apply(eb, _ctx(self.root))

        self.assertEqual(eb.values[handler.KEY], str(self.root / handler.RELATIVE))


if __name__ == "__main__":
    unittest.main()
