from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.env.builder import build_env
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache import conf as handler
from utils.env.handlers.infinito.cache import pin as pin_handler


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

    @patch.dict(
        os.environ,
        {handler.KEY: "", pin_handler.KEY: "", pin_handler.ROOT_KEY: ""},
        clear=False,
    )
    def test_the_map_lives_outside_the_checkout_below_the_pin_root(self) -> None:
        eb = EnvBuilder()
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data")}):
            pin_handler.apply(eb, _ctx(self.root / "checkout"))
            handler.finalize(eb)

        self.assertEqual(
            eb.values[handler.KEY],
            str(self.root / "data" / "infinito" / "cache" / "upstreams.conf"),
        )
        self.assertFalse(
            Path(eb.values[handler.KEY]).is_relative_to(self.root / "checkout")
        )

    @patch.dict(
        os.environ,
        {handler.KEY: "", pin_handler.KEY: "", pin_handler.ROOT_KEY: ""},
        clear=False,
    )
    def test_a_custom_env_pin_root_moves_the_map_with_the_checkouts(self) -> None:
        checkout = self.root / "checkout"
        checkout.mkdir()
        custom_root = self.root / "custom" / "cache"
        (checkout / "custom.env").write_text(
            f"{pin_handler.ROOT_KEY}={custom_root}\n", encoding="utf-8"
        )
        with (
            patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data")}),
            patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
            patch("utils.env.handlers.infinito.inventory.run_helper", return_value=""),
        ):
            eb = build_env({"INFINITO_DISTRO": "debian"}, repo_root=checkout)

        self.assertEqual(eb.values[pin_handler.ROOT_KEY], str(custom_root))
        self.assertEqual(eb.values[handler.KEY], str(custom_root / "upstreams.conf"))


class TestPinPaths(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            pin_handler.KEY: "",
            pin_handler.ROOT_KEY: "",
            "XDG_STATE_HOME": "/xdg/state",
            "XDG_DATA_HOME": "/xdg/data",
        },
        clear=False,
    )
    def test_the_xdg_base_directories_hold_the_pin_and_its_checkouts(self) -> None:
        eb = EnvBuilder()
        pin_handler.apply(eb, _ctx(Path("/checkout")))
        self.assertEqual(eb.values[pin_handler.KEY], "/xdg/state/infinito/cache.ref")
        self.assertEqual(eb.values[pin_handler.ROOT_KEY], "/xdg/data/infinito/cache")

    @patch.dict(
        os.environ,
        {
            pin_handler.KEY: "",
            pin_handler.ROOT_KEY: "",
            "XDG_STATE_HOME": "/xdg/state",
            "XDG_DATA_HOME": "/xdg/data",
        },
        clear=False,
    )
    def test_a_default_env_value_wins_over_the_xdg_derivation(self) -> None:
        eb = EnvBuilder()
        ctx = BuildContext(
            static={pin_handler.KEY: "/pinned/cache.ref", pin_handler.ROOT_KEY: ""},
            static_comments={pin_handler.KEY: "pin file"},
            repo_root=Path("/checkout"),
            on_gha=False,
            on_act=False,
        )
        pin_handler.apply(eb, ctx)
        self.assertEqual(eb.values[pin_handler.KEY], "/pinned/cache.ref")
        self.assertEqual(eb.values[pin_handler.ROOT_KEY], "/xdg/data/infinito/cache")
        self.assertEqual(eb.comments[pin_handler.KEY], "pin file")
        self.assertEqual(
            pin_handler.STATIC_READS, (pin_handler.KEY, pin_handler.ROOT_KEY)
        )

    @patch.dict(
        os.environ,
        {
            pin_handler.KEY: "",
            pin_handler.ROOT_KEY: "",
            "HOME": "/home/dev",
            "XDG_STATE_HOME": "relative/state",
            "XDG_DATA_HOME": "",
        },
        clear=False,
    )
    def test_an_unset_or_relative_xdg_value_falls_back_to_home(self) -> None:
        eb = EnvBuilder()
        pin_handler.apply(eb, _ctx(Path("/checkout")))
        self.assertEqual(
            eb.values[pin_handler.KEY], "/home/dev/.local/state/infinito/cache.ref"
        )
        self.assertEqual(
            eb.values[pin_handler.ROOT_KEY], "/home/dev/.local/share/infinito/cache"
        )


if __name__ == "__main__":
    unittest.main()
