"""Unit tests for :mod:`utils.env.handlers.infinito.package_cache.url`."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import apply_custom_env
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers import ORDERED_HANDLERS
from utils.env.handlers.infinito.package_cache import url as handler

RUNNER_IP = "10.47.0.2"
PORT = "8081"
NEXUS = f"http://{RUNNER_IP}:{PORT}"
OVERRIDE = "http://127.0.0.1:8081"
BLANK = {
    handler.KEY: "",
    handler.STACK_KEY: "",
    handler.IP_KEY: "",
    handler.PORT_KEY: "",
}


def _url(stack: str, root: Path = Path("/repo")) -> str:
    eb = EnvBuilder()
    eb.set(handler.STACK_KEY, stack)
    eb.set(handler.IP_KEY, RUNNER_IP)
    eb.set(handler.PORT_KEY, PORT)
    handler.apply(
        eb,
        BuildContext(
            static={},
            static_comments={},
            repo_root=root,
            on_gha=False,
            on_act=False,
        ),
    )
    apply_custom_env(eb, root)
    return eb.values[handler.KEY]


class TestPackageCacheUrl(unittest.TestCase):
    @patch.dict(os.environ, BLANK, clear=False)
    def test_the_cache_stack_points_the_url_at_the_runners_nexus(self) -> None:
        self.assertEqual(_url("true"), NEXUS)

    @patch.dict(os.environ, BLANK, clear=False)
    def test_without_the_cache_stack_the_url_is_empty(self) -> None:
        self.assertEqual(_url("false"), "")

    @patch.dict(os.environ, {**BLANK, handler.KEY: NEXUS})
    def test_a_stale_url_is_recomputed_once_the_stack_is_off(self) -> None:
        self.assertEqual(_url("false"), "")

    @patch.dict(os.environ, {**BLANK, handler.KEY: OVERRIDE})
    def test_a_stale_override_is_recomputed_once_the_stack_is_on(self) -> None:
        self.assertEqual(_url("true"), NEXUS)

    @patch.dict(os.environ, BLANK, clear=False)
    def test_a_custom_env_url_wins(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "custom.env").write_text(
                f"{handler.KEY}={OVERRIDE}\n", encoding="utf-8"
            )
            self.assertEqual(_url("false", Path(root)), OVERRIDE)

    def test_the_handler_runs_after_the_stack_the_address_and_the_port(
        self,
    ) -> None:
        names = [module.__name__ for module in ORDERED_HANDLERS]
        position = names.index(handler.__name__)
        for earlier in ("stack", "infra", "passthrough"):
            with self.subTest(earlier=earlier):
                index = next(
                    i for i, name in enumerate(names) if name.endswith(f".{earlier}")
                )
                self.assertLess(index, position)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
