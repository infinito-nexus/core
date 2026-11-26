from __future__ import annotations

import unittest
from unittest.mock import patch

from . import test_client as client_suite
from . import test_mcp as mcp_suite

SCRIPTS = (("client", client_suite), ("mcp", mcp_suite))
MANAGED = {"id": "old", "label": "infinito:mcp"}


class TestApiKeyContract(unittest.TestCase):
    def _deleted_keys(self, suite, keys) -> list[str]:
        module = suite.load_script()
        api = suite.FakeApi(keys=keys)
        with patch.object(module, "call", api):
            module.main()
        return api.deleted_keys

    def _aborts(self, suite, prefix: str, answer: dict, needle: str) -> None:
        module = suite.load_script()
        api = suite.FakeApi()
        listings = []

        # Exception: stuck replaces the script's call() and keeps its signature, whose method defaults to GET for the scripts' bare call(path) reads.
        def stuck(path, method="GET", payload=None, api_key=None):
            if path.startswith(prefix):
                listings.append(path)
                if len(listings) > 3:
                    raise AssertionError(f"the listing {prefix} never ends")
                return 200, answer
            return api(path, method, payload, api_key)

        with (
            patch.object(module, "call", stuck),
            self.assertRaises(SystemExit) as exit_,
        ):
            module.main()
        self.assertIn(needle, str(exit_.exception))

    def test_the_run_leaves_no_api_key_behind(self) -> None:
        for name, suite in SCRIPTS:
            with self.subTest(script=name):
                self.assertEqual(["k1"], self._deleted_keys(suite, ()))

    def test_a_stale_managed_key_behind_a_full_page_is_still_replaced(self) -> None:
        for name, suite in SCRIPTS:
            humans = [
                {"id": f"h{n}", "label": f"human {n}"} for n in range(suite.PAGE_SIZE)
            ]
            with self.subTest(script=name):
                self.assertEqual(
                    ["old", "k1"], self._deleted_keys(suite, [*humans, MANAGED])
                )

    def test_a_stale_managed_key_behind_a_full_filtered_page_is_still_replaced(
        self,
    ) -> None:
        for name, suite in SCRIPTS:
            near = [
                {"id": f"n{n}", "label": f"infinito:mcp-copy-{n}"}
                for n in range(suite.MAX_PAGE_SIZE)
            ]
            with self.subTest(script=name):
                self.assertEqual(
                    ["old", "k1"], self._deleted_keys(suite, [*near, MANAGED])
                )

    def test_a_repeated_workflow_cursor_aborts_rather_than_loops(self) -> None:
        for name, suite in SCRIPTS:
            with self.subTest(script=name):
                self._aborts(
                    suite,
                    "/api/v1/workflows?",
                    {"data": [], "nextCursor": "same"},
                    "nextCursor repeats",
                )

    def test_a_key_listing_that_ignores_skip_aborts_rather_than_loops(self) -> None:
        for name, suite in SCRIPTS:
            full = [
                {"id": f"n{n}", "label": f"infinito:mcp-copy-{n}"}
                for n in range(suite.MAX_PAGE_SIZE)
            ]
            with self.subTest(script=name):
                self._aborts(
                    suite, "/rest/api-keys?", {"data": {"items": full}}, "repeats"
                )


if __name__ == "__main__":
    unittest.main()
