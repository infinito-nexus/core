"""Unit tests for `utils.cache.records`.

The ansible ``cache_records`` lookup runs inside the deploy container, which
is handed a curated environment and never sources ``.env``, so the Ubuntu
mirror list has to resolve off ``default.env`` alone.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from utils.cache.records import MIRRORS_KEY, PLACEHOLDER, records


class TestRecords(unittest.TestCase):
    def test_resolves_without_the_mirror_key_in_the_environment(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop(MIRRORS_KEY, None)
            rendered = records()
        self.assertTrue(
            rendered,
            f"{MIRRORS_KEY} did not resolve from default.env, so every "
            "repository record is dropped and the Nexus bootstrap has nothing "
            "to create",
        )
        self.assertNotIn(PLACEHOLDER, rendered)

    def test_the_process_environment_wins(self) -> None:
        with patch.dict(
            os.environ,
            {MIRRORS_KEY: "http://primary.test/ubuntu/ http://fallback.test/ubuntu/"},
        ):
            rendered = records()
        self.assertIn("|http://primary.test/ubuntu|", rendered)
        self.assertIn("|http://fallback.test/ubuntu|", rendered)
