"""Unit tests for ``plugins/lookup/postgres_libraries.py``."""

import importlib.util
import unittest

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class PostgresLibrariesLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module(
            "plugins/lookup/postgres_libraries.py",
            "lookup_postgres_libraries",
        )

    def _run(self, terms):
        lookup = self.mod.LookupModule()
        return lookup.run(terms)

    def test_zero_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self._run([])

    def test_two_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self._run([["vector"], "extra"])

    def test_non_list_first_term_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["vector"])

    def test_empty_extension_list_returns_empty(self):
        result = self._run([[]])
        self.assertEqual(result, [[]])

    def test_extension_in_registry_returns_recipe(self):
        result = self._run([["vector"]])[0]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["extension"], "vector")
        self.assertEqual(result[0]["name"], "pgvector")
        self.assertIn("git_source", result[0])

    def test_base_extensions_are_filtered_out(self):
        result = self._run([["bloom", "postgis", "pg_trgm", "unaccent"]])[0]
        self.assertEqual(result, [])

    def test_mixed_extensions_returns_only_non_base(self):
        result = self._run([["bloom", "vector", "postgis"]])[0]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["extension"], "vector")

    def test_duplicates_are_deduplicated(self):
        result = self._run([["vector", "vector"]])[0]
        self.assertEqual(len(result), 1)

    def test_blanks_are_skipped(self):
        result = self._run([["", "  ", "vector"]])[0]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["extension"], "vector")


if __name__ == "__main__":
    unittest.main()
