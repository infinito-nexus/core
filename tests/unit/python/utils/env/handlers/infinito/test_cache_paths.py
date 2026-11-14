"""Unit tests for the shared cache folder :mod:`utils.env.handlers.infinito.cache.paths` writes."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import apply_custom_env
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers import passthrough
from utils.env.handlers.infinito.cache import paths as handler
from utils.paths import read_group_path

KEY = "INFINITO_CACHE_SHARED_HOST_PATH"


def _context(static: dict[str, str], repo_root: Path) -> BuildContext:
    """Build the context the handlers read.

    Args:
        static: the parsed default.env values.
        repo_root: the checkout whose custom.env applies.
    """
    return BuildContext(
        static=static,
        static_comments={},
        repo_root=repo_root,
        on_gha=False,
        on_act=False,
    )


def _derived() -> str:
    return str(Path(read_group_path("DIR_CACHE")) / "shared")


@patch.dict(os.environ, {KEY: ""}, clear=False)
class TestSharedCachePath(unittest.TestCase):
    def test_the_shared_folder_defaults_below_the_cache_base(self) -> None:
        eb = EnvBuilder()
        handler.apply(eb, _context({}, Path("/repo")))
        self.assertEqual(eb.values[KEY], _derived())

    def test_the_empty_default_env_entry_does_not_mask_the_derived_folder(
        self,
    ) -> None:
        eb = EnvBuilder()
        ctx = _context({KEY: ""}, Path("/repo"))
        passthrough.apply(eb, ctx)
        handler.apply(eb, ctx)
        self.assertEqual(eb.values[KEY], _derived())

    def test_an_exported_path_wins(self) -> None:
        eb = EnvBuilder()
        with patch.dict(os.environ, {KEY: "/srv/exported"}, clear=False):
            handler.apply(eb, _context({}, Path("/repo")))
        self.assertEqual(eb.values[KEY], "/srv/exported")

    def test_a_custom_env_path_replaces_the_derived_folder(self) -> None:
        eb = EnvBuilder()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "custom.env").write_text(f"{KEY}=/srv/custom\n")
            handler.apply(eb, _context({}, root))
            derived = eb.values[KEY]
            apply_custom_env(eb, root)
        self.assertEqual(
            [derived, eb.values[KEY]],
            [_derived(), "/srv/custom"],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
