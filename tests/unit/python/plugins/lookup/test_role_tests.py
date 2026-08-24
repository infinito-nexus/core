"""Unit tests for the `role_tests` lookup plugin.

Pins the contract: two terms (application_id, dotted path), values read
from ``roles/<application_id>/meta/tests.yml`` under ``playbook_dir``,
missing file/key falls back to the ``default`` kwarg.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup.role_tests import LookupModule
from utils.cache.yaml import dump_yaml
from utils.roles.mapping import ROLE_FILE_META_TESTS


class TestRoleTestsLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.root = Path(cls._tmp.name)
        tests_yml = cls.root / "roles" / "svc-runner" / ROLE_FILE_META_TESTS
        tests_yml.parent.mkdir(parents=True)
        dump_yaml(tests_yml, {"cli": {"timeout": 9000}})

    def _run(self, terms, **kwargs):
        return LookupModule().run(
            terms, variables={"playbook_dir": str(self.root)}, **kwargs
        )

    def test_reads_dotted_value(self):
        self.assertEqual(self._run(["svc-runner", "cli.timeout"]), [9000])

    def test_missing_key_returns_default(self):
        self.assertEqual(self._run(["svc-runner", "cli.missing"], default=3600), [3600])

    def test_missing_file_returns_default(self):
        self.assertEqual(self._run(["web-app-x", "cli.timeout"], default=""), [""])

    def test_missing_default_is_none(self):
        self.assertEqual(self._run(["web-app-x", "cli.timeout"]), [None])

    def test_requires_two_terms(self):
        with self.assertRaises(AnsibleError):
            self._run(["svc-runner"])
        with self.assertRaises(AnsibleError):
            self._run(["svc-runner", "cli.timeout", "extra"])

    def test_requires_playbook_dir(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run(["svc-runner", "cli.timeout"], variables={})


if __name__ == "__main__":
    unittest.main()
