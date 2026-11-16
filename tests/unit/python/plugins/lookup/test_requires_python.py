from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup import requires_python as plugin


class TestRequiresPythonLookup(unittest.TestCase):
    def test_the_lookup_returns_the_pyproject_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "pyproject.toml").write_text(
                '[project]\nname = "demo"\nrequires-python = ">=3.12,<3.14"\n',
                encoding="utf-8",
            )
            with unittest.mock.patch.object(plugin, "PROJECT_ROOT", Path(tmp)):
                self.assertEqual(plugin.LookupModule().run([]), [">=3.12,<3.14"])

    def test_the_lookup_takes_no_terms(self) -> None:
        with self.assertRaises(AnsibleError):
            plugin.LookupModule().run(["range"])


if __name__ == "__main__":
    unittest.main()
