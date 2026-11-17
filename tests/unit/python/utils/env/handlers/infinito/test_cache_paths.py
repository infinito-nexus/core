"""Unit tests for the cache base and the folders :mod:`utils.env.handlers.infinito.cache.paths` writes."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import apply_custom_env, build_env
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers import passthrough
from utils.env.handlers.infinito.cache import paths as handler
from utils.env.handlers.infinito.tools.idle import STAMP_DIR_KEY
from utils.env.handlers.infinito.tools.models import KEY as MODELS_KEY
from utils.env.parser import parse_static_env_with_comments
from utils.paths import PROJECT_ROOT, read_group_path

KEY = "INFINITO_CACHE_SHARED_HOST_PATH"
DEFAULT_ENV = PROJECT_ROOT / "default.env"


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


@patch.dict(os.environ, {KEY: "", handler.BASE_KEY: ""}, clear=False)
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


@patch.dict(
    os.environ,
    {handler.BASE_KEY: "", **{key: "" for key, _legs, _comment in handler.ENTRIES}},
    clear=False,
)
class TestExportedCacheBase(unittest.TestCase):
    def test_an_exported_base_moves_every_entry_below_it(self) -> None:
        eb = EnvBuilder()
        with patch.dict(os.environ, {handler.BASE_KEY: "/mnt/cache"}, clear=False):
            handler.apply(eb, _context({}, Path("/repo")))
        self.assertEqual(
            {key: eb.values[key] for key, _legs, _comment in handler.ENTRIES},
            {
                key: str(Path("/mnt/cache").joinpath(*legs))
                for key, legs, _comment in handler.ENTRIES
            },
        )

    def test_an_exported_leg_still_wins_over_the_moved_base(self) -> None:
        eb = EnvBuilder()
        exported = {handler.BASE_KEY: "/mnt/cache", KEY: "/srv/shared"}
        with patch.dict(os.environ, exported, clear=False):
            handler.apply(eb, _context({}, Path("/repo")))
        self.assertEqual(eb.values[KEY], "/srv/shared")

    def test_without_an_exported_base_the_paths_spot_decides(self) -> None:
        self.assertEqual(handler.base(), Path(read_group_path("DIR_CACHE")))

    def test_the_base_itself_is_recorded_for_the_runner_to_bind(self) -> None:
        eb = EnvBuilder()
        handler.apply(eb, _context({}, Path("/repo")))
        self.assertEqual(eb.values[handler.BASE_KEY], read_group_path("DIR_CACHE"))

    def test_a_padded_export_is_stripped_as_every_other_key_is(self) -> None:
        eb = EnvBuilder()
        with patch.dict(os.environ, {handler.BASE_KEY: " /mnt/cache \n"}):
            handler.apply(eb, _context({}, Path("/repo")))
            resolved = handler.base()
        self.assertEqual(
            [resolved, eb.values[handler.BASE_KEY], eb.values[KEY]],
            [Path("/mnt/cache"), "/mnt/cache", "/mnt/cache/shared"],
        )

    def test_an_exported_base_leaves_the_machine_place_where_the_spot_puts_it(
        self,
    ) -> None:
        with patch.dict(os.environ, {handler.BASE_KEY: "/mnt/cache"}):
            self.assertEqual(
                [handler.base(), handler.machine()],
                [Path("/mnt/cache"), Path(read_group_path("DIR_CACHE"))],
            )

    def test_every_cache_path_follows_the_base_through_the_whole_build(self) -> None:
        static, comments = parse_static_env_with_comments(DEFAULT_ENV)
        derived = (MODELS_KEY, STAMP_DIR_KEY)
        exported = {handler.BASE_KEY: "/mnt/cache", **dict.fromkeys(derived, "")}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, exported):
            values = build_env(static, Path(tmp), comments=comments).values
        for key in (*(key for key, _legs, _note in handler.ENTRIES), *derived):
            with self.subTest(key=key):
                self.assertTrue(Path(values[key]).is_relative_to("/mnt/cache"))

    def _built_with_custom(self, custom: str) -> dict[str, str]:
        """Args:
            custom: the checkout's custom.env text; nothing is exported.

        Returns:
            The values ``make dotenv`` writes into .env.
        """
        static, comments = parse_static_env_with_comments(DEFAULT_ENV)
        derived = (MODELS_KEY, STAMP_DIR_KEY)
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, dict.fromkeys(derived, "")),
        ):
            (Path(tmp) / "custom.env").write_text(custom, encoding="utf-8")
            return build_env(static, Path(tmp), comments=comments).values

    def test_a_custom_env_base_moves_every_cache_path_with_it(self) -> None:
        values = self._built_with_custom(f"{handler.BASE_KEY}=/mnt/cache\n")
        legs = (*(key for key, _legs, _note in handler.ENTRIES), MODELS_KEY)
        self.assertEqual(values[handler.BASE_KEY], "/mnt/cache")
        for key in (*legs, STAMP_DIR_KEY):
            with self.subTest(key=key):
                self.assertTrue(Path(values[key]).is_relative_to("/mnt/cache"))

    def test_a_custom_env_leg_still_wins_over_its_custom_env_base(self) -> None:
        values = self._built_with_custom(
            f"{handler.BASE_KEY}=/mnt/cache\n{KEY}=/srv/shared\n"
        )
        self.assertEqual(
            [values[handler.BASE_KEY], values[KEY]], ["/mnt/cache", "/srv/shared"]
        )


class TestDefaultEnvHardCodesNoCachePath(unittest.TestCase):
    def test_no_static_value_names_the_cache_base(self) -> None:
        spot = read_group_path("DIR_CACHE")
        static, _comments = parse_static_env_with_comments(DEFAULT_ENV)
        self.assertEqual({k: v for k, v in static.items() if spot in v}, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
