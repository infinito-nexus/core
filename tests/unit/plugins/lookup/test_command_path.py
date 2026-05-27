from __future__ import annotations

import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.command_path import LookupModule


class TestCommandPathLookup(unittest.TestCase):
    def setUp(self):
        self.plugin = LookupModule()

    def test_requires_at_least_one_term(self):
        with self.assertRaises(AnsibleError):
            self.plugin.run([])

    def test_resolves_single_command(self):
        with patch(
            "plugins.lookup.command_path.shutil.which",
            return_value="/usr/local/bin/gitcon",
        ):
            out = self.plugin.run(["gitcon"])
        self.assertEqual(out, ["/usr/local/bin/gitcon"])

    def test_resolves_multiple_commands(self):
        def _fake_which(cmd, path=None):
            return f"/usr/local/bin/{cmd}"

        with patch("plugins.lookup.command_path.shutil.which", side_effect=_fake_which):
            out = self.plugin.run(["baudolo", "baudolo-seed"])
        self.assertEqual(out, ["/usr/local/bin/baudolo", "/usr/local/bin/baudolo-seed"])

    def test_rejects_whitespace_command(self):
        with self.assertRaises(AnsibleError):
            self.plugin.run(["setup-hibernate --help"])

    def test_missing_command_raises(self):
        with (
            patch("plugins.lookup.command_path.shutil.which", return_value=None),
            self.assertRaises(AnsibleError),
        ):
            self.plugin.run(["does-not-exist"])

    def test_custom_path_argument_is_passed_to_which(self):
        with patch(
            "plugins.lookup.command_path.shutil.which", return_value="/custom/bin/tool"
        ) as which:
            out = self.plugin.run(["tool"], path="/custom/bin:/usr/bin")
        self.assertEqual(out, ["/custom/bin/tool"])
        which.assert_called_once_with("tool", path="/custom/bin:/usr/bin")


if __name__ == "__main__":
    unittest.main()
