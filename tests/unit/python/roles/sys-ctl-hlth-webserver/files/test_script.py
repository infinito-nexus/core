import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


def load_module_from_path(mod_name: str, path: str):
    """Dynamically load a module from a filesystem path."""
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def _target(codes, scheme="https", timeout=10):
    return {"codes": codes, "scheme": scheme, "timeout": timeout}


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class TestStandaloneCheckerScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import PROJECT_ROOT

        cls.script_path = str(
            PROJECT_ROOT
            / "roles"
            / "sys-ctl-hlth-webserver"
            / "files"
            / "python"
            / "script.py"
        )
        if not Path(cls.script_path).is_file():
            raise FileNotFoundError(f"Cannot find script.py at {cls.script_path}")
        cls.script = load_module_from_path("health_script", cls.script_path)

    def test_rejects_invalid_json(self):
        with self.assertRaises(SystemExit):
            self.script.main(["--targets", '{"bad json": {'])

    def test_rejects_non_mapping_json(self):
        with self.assertRaises(SystemExit):
            self.script.main(["--targets", '["not", "a", "mapping"]'])

    def test_rejects_unknown_scheme(self):
        with self.assertRaises(SystemExit):
            self.script.main(
                ["--targets", json.dumps({"a.example.org": _target([200], "ftp")})]
            )

    def test_rejects_missing_timeout(self):
        with self.assertRaises(SystemExit):
            self.script.main(
                [
                    "--targets",
                    json.dumps({"a.example.org": {"codes": [200], "scheme": "https"}}),
                ]
            )

    @patch("requests.head")
    def test_all_ok_returns_zero(self, mock_head):
        statuses = {"ok1.example.org": 200, "ok2.example.org": 301}
        mock_head.side_effect = lambda url, **_: _Response(
            statuses[url.split("://", 1)[1]]
        )

        exit_code, output = self._run_main(
            {
                "ok1.example.org": _target([200, 302, 301]),
                "ok2.example.org": _target([301]),
            }
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("ok1.example.org: OK", output)
        self.assertIn("ok2.example.org: OK", output)

    @patch("requests.head")
    def test_mismatches_counted(self, mock_head):
        mock_head.side_effect = lambda url, **_: _Response(200)

        exit_code, output = self._run_main(
            {"bad.example.org": _target([404]), "ok.example.org": _target([200])}
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("bad.example.org: ERROR: Expected [404]. Got 200.", output)

    @patch("requests.head")
    def test_non_list_codes_sanitize_to_empty_and_fail(self, mock_head):
        mock_head.side_effect = lambda url, **_: _Response(200)

        exit_code, output = self._run_main({"foo.example.org": _target("not-a-list")})
        self.assertEqual(exit_code, 1)
        self.assertIn(
            "foo.example.org: ERROR: No expectations provided. Got 200.", output
        )

    @patch("requests.head")
    def test_each_domain_uses_its_own_scheme_and_timeout(self, mock_head):
        seen = {}

        def head(url, allow_redirects=False, timeout=None, verify=True):
            seen[url.split("://", 1)[1]] = (url, timeout)
            return _Response(200)

        mock_head.side_effect = head

        exit_code, _ = self._run_main(
            {
                "clear.example.org": _target([200], "https", 10),
                "svc.abcd1234efgh.onion": _target([200], "http", 30),
            }
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            seen["svc.abcd1234efgh.onion"], ("http://svc.abcd1234efgh.onion", 30)
        )
        self.assertEqual(seen["clear.example.org"], ("https://clear.example.org", 10))

    def _run_main(self, targets):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = self.script.main(["--targets", json.dumps(targets)])
        return exit_code, buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
