from __future__ import annotations

import unittest

from cli.administration.deploy.dedicated import command as dedicated_main


class TestDedicatedMainParser(unittest.TestCase):
    def test_build_parser_has_expected_core_args(self):
        parser = dedicated_main.build_parser()

        # Smoke-check: parser exists and has some core options
        opts = {a.dest for a in parser._actions}

        self.assertIn("inventory", opts)
        self.assertIn("limit", opts)
        self.assertIn("password_file", opts)
        self.assertIn("skip_build", opts)
        self.assertIn("id", opts)
        self.assertIn("verbose", opts)
        self.assertIn("diff", opts)

        # Removed in the refactor
        self.assertNotIn("logs", opts)


if __name__ == "__main__":
    unittest.main()
