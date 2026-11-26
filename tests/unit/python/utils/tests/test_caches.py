from __future__ import annotations

import contextlib
import unittest
import unittest.mock

from utils.cache import applications, domains
from utils.cache import yaml as yaml_cache
from utils.tests.caches import fresh_caches, reset_caches

KEY = "utils-tests-caches-sentinel"
PARSED = (applications._APPLICATIONS_DEFAULTS_CACHE, yaml_cache._CACHE)
RENDERED = (applications._MERGED_APPLICATIONS_CACHE, domains._MERGED_DOMAINS_CACHE)


class TestResetCaches(unittest.TestCase):
    def setUp(self) -> None:
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for cache in (*PARSED, *RENDERED):
            stack.enter_context(unittest.mock.patch.dict(cache, {KEY: {}}))

    def test_unchanged_files_keep_the_parsed_caches(self) -> None:
        reset_caches(files_changed=False)
        self.assertEqual([True, True], [KEY in cache for cache in PARSED])
        self.assertEqual([False, False], [KEY in cache for cache in RENDERED])

    def test_changed_files_drop_every_cache(self) -> None:
        reset_caches(files_changed=True)
        self.assertEqual([False] * 4, [KEY in cache for cache in (*PARSED, *RENDERED)])

    def test_fresh_caches_resets_on_entry_and_on_a_failing_exit(self) -> None:
        with self.assertRaises(RuntimeError), fresh_caches(files_changed=False):
            self.assertNotIn(KEY, RENDERED[0])
            RENDERED[0][KEY] = {}
            raise RuntimeError
        self.assertNotIn(KEY, RENDERED[0])
        self.assertIn(KEY, PARSED[0])


if __name__ == "__main__":
    unittest.main()
