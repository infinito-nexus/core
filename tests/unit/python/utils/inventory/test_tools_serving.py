"""Unit tests for utils.inventory.tools.serving."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from utils.inventory import tools
from utils.inventory.tools import LIBRETRANSLATE_ROLE, S1_ROLE, serving

ROOT = Path("/nowhere")
ENGINE_LANGUAGES = b'[{"code": "de"}, {"code": "en"}]'


class TestServing(unittest.TestCase):
    def _run(self, answers: dict[str, bytes | None], roles: tuple[str, ...]) -> bool:
        with (
            patch.object(tools, "host_url", lambda root, role, key: f"http://{role}"),
            patch.object(tools, "_answers", answers.get),
        ):
            return serving(ROOT, ["de"], roles)

    def test_engine_alone_does_not_speak_for_system_one(self) -> None:
        self.assertFalse(
            self._run(
                {f"http://{LIBRETRANSLATE_ROLE}/languages": ENGINE_LANGUAGES},
                (LIBRETRANSLATE_ROLE, S1_ROLE),
            )
        )

    def test_both_answering_is_serving(self) -> None:
        self.assertTrue(
            self._run(
                {
                    f"http://{LIBRETRANSLATE_ROLE}/languages": ENGINE_LANGUAGES,
                    f"http://{S1_ROLE}/health": b"ok",
                },
                (LIBRETRANSLATE_ROLE, S1_ROLE),
            )
        )

    def test_a_role_nobody_asked_for_is_not_probed(self) -> None:
        self.assertTrue(self._run({f"http://{S1_ROLE}/health": b"ok"}, (S1_ROLE,)))

    def test_a_missing_language_still_fails_the_engine(self) -> None:
        self.assertFalse(
            self._run(
                {
                    f"http://{LIBRETRANSLATE_ROLE}/languages": b'[{"code": "en"}]',
                    f"http://{S1_ROLE}/health": b"ok",
                },
                (LIBRETRANSLATE_ROLE, S1_ROLE),
            )
        )


if __name__ == "__main__":
    unittest.main()
