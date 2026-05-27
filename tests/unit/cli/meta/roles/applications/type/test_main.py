from __future__ import annotations

import io
from unittest import TestCase, main
from unittest.mock import patch

import cli.meta.roles.applications.type.__main__ as mod


class TestCliMetaApplicationsType(TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            try:
                # Patch argparse by patching sys.argv
                with patch("sys.argv", ["prog", *argv]):
                    mod.main()
                return 0, out.getvalue(), err.getvalue()
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
                return code, out.getvalue(), err.getvalue()

    def test_json_all_groups(self) -> None:
        fake = {"server": ["a"], "workstation": ["b"], "universal": ["c"]}
        with patch.object(mod, "list_invokables_by_type", return_value=fake):
            code, out, err = self._run(["--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn('"server"', out)
        self.assertIn('"workstation"', out)
        self.assertIn('"universal"', out)

    def test_json_single_type(self) -> None:
        fake = {"server": ["a", "x"], "workstation": ["b"], "universal": ["c"]}
        with patch.object(mod, "list_invokables_by_type", return_value=fake):
            code, out, err = self._run(["--format", "json", "--type", "server"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn('"a"', out)
        self.assertIn('"x"', out)
        self.assertNotIn('"server"', out)  # should be a list, not dict

    def test_text_single_type(self) -> None:
        fake = {"server": ["a", "x"], "workstation": ["b"], "universal": ["c"]}
        with patch.object(mod, "list_invokables_by_type", return_value=fake):
            code, out, err = self._run(["--type", "server"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out.strip().splitlines(), ["a", "x"])

    def test_lifecycles_are_forwarded(self) -> None:
        fake = {"server": ["a"], "workstation": [], "universal": []}
        with patch.object(mod, "list_invokables_by_type", return_value=fake) as mocked:
            code, out, err = self._run(
                [
                    "--format",
                    "json",
                    "--type",
                    "server",
                    "--lifecycles",
                    "alpha",
                    "beta",
                    "RC",
                    " stable ",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(err, "")

        # Ensure lifecycles normalization + forwarding happened
        mocked.assert_called_once()
        _args, kwargs = mocked.call_args
        self.assertIn("lifecycles", kwargs)
        self.assertEqual(kwargs["lifecycles"], {"alpha", "beta", "rc", "stable"})

        # Output still correct
        self.assertIn('"a"', out)

    def test_error_handling(self) -> None:
        with patch.object(
            mod, "list_invokables_by_type", side_effect=RuntimeError("boom")
        ):
            code, out, err = self._run(["--format", "json"])
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("Error:", err)


if __name__ == "__main__":
    main()
