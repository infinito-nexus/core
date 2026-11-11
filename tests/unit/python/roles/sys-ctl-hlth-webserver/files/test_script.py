import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import read_text


def load_module_from_path(mod_name: str, path: str):
    """Dynamically load a module from a filesystem path."""
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def _target(codes, scheme="https", timeout=10, paused_marker="", application_id=""):
    return {
        "codes": codes,
        "scheme": scheme,
        "timeout": timeout,
        "paused_marker": paused_marker,
        "application_id": application_id,
    }


PUBLISHED = (
    "web-app-ok",
    "web-app-odd",
    "web-app-bad",
    "web-app-gone",
    "web-app-p",
    "web-app-x",
)


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

    def setUp(self):
        self._status_dir = tempfile.TemporaryDirectory()
        self.status_file = Path(self._status_dir.name) / "status.json"

    def tearDown(self):
        self._status_dir.cleanup()

    def _argv(self, targets_json, published):
        return [
            "--targets",
            targets_json,
            "--status-file",
            str(self.status_file),
            "--status-applications",
            json.dumps(list(published)),
        ]

    def _assert_refused(self, targets_json, reason):
        with self.assertRaises(SystemExit) as raised:
            self.script.main(self._argv(targets_json, PUBLISHED))
        self.assertIn(reason, str(raised.exception.code))

    def test_rejects_invalid_json(self):
        self._assert_refused('{"bad json": {', "valid JSON")

    def test_rejects_non_mapping_json(self):
        self._assert_refused('["not", "a", "mapping"]', "JSON object")

    def test_rejects_unknown_scheme(self):
        self._assert_refused(
            json.dumps({"a.example.org": _target([200], "ftp")}), "scheme"
        )

    def test_rejects_missing_timeout(self):
        self._assert_refused(
            json.dumps({"a.example.org": {"codes": [200], "scheme": "https"}}),
            "timeout",
        )

    def test_rejects_missing_paused_marker(self):
        self._assert_refused(
            json.dumps(
                {"a.example.org": {"codes": [200], "scheme": "https", "timeout": 10}}
            ),
            "paused_marker",
        )

    def test_rejects_missing_application_id(self):
        target = _target([200])
        del target["application_id"]
        self._assert_refused(json.dumps({"a.example.org": target}), "application_id")

    def test_requires_a_status_file(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            self.script.main(
                ["--targets", json.dumps({}), "--status-applications", "[]"]
            )

    def test_rejects_published_ids_that_are_not_a_list_of_strings(self):
        with self.assertRaises(SystemExit) as raised:
            self.script.main(
                [
                    "--targets",
                    json.dumps({}),
                    "--status-file",
                    str(self.status_file),
                    "--status-applications",
                    json.dumps({"web-app-ok": True}),
                ]
            )
        self.assertIn("list of strings", str(raised.exception.code))

    @patch("requests.head")
    def test_the_document_names_only_published_applications_and_no_code(
        self, mock_head
    ):
        mock_head.side_effect = lambda url, **_: _Response(200)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.script.main(
                self._argv(
                    json.dumps(
                        {
                            "card.example.org": _target(
                                [200], application_id="web-app-ok"
                            ),
                            "admin.example.org": _target(
                                [200], application_id="web-app-secret"
                            ),
                        }
                    ),
                    published=["web-app-ok"],
                )
            )
        applications = self._status()["applications"]
        self.assertEqual(list(applications), ["web-app-ok"])
        self.assertEqual(set(applications["web-app-ok"]), {"state", "checked"})

    @patch("requests.head")
    def test_a_published_card_without_a_target_is_reported_and_left_unknown(
        self, mock_head
    ):
        mock_head.side_effect = lambda url, **_: _Response(200)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = self.script.main(
                self._argv(
                    json.dumps(
                        {"ok.example.org": _target([200], application_id="web-app-ok")}
                    ),
                    published=["web-app-ok", "web-app-headless"],
                )
            )
        self.assertEqual(code, 0)
        self.assertIn(
            "web-app-headless: NO TARGET: its dashboard badge reads unknown.",
            buffer.getvalue().splitlines(),
        )
        self.assertNotIn("web-app-ok: NO TARGET", buffer.getvalue())
        self.assertEqual(list(self._status()["applications"]), ["web-app-ok"])

    @patch("requests.head")
    def test_status_document_names_the_state_of_every_application(self, mock_head):
        codes = {"ok.example.org": 200, "odd.example.org": 404, "bad.example.org": 502}
        mock_head.side_effect = lambda url, **_: _Response(
            codes[url.split("://", 1)[1]]
        )

        self._run_main(
            {
                "ok.example.org": _target([200], application_id="web-app-ok"),
                "odd.example.org": _target([200], application_id="web-app-odd"),
                "bad.example.org": _target([200], application_id="web-app-bad"),
            }
        )

        applications = self._status()["applications"]
        self.assertEqual(
            {app: entry["state"] for app, entry in applications.items()},
            {"web-app-ok": "running", "web-app-odd": "degraded", "web-app-bad": "down"},
        )

    @patch("requests.head")
    def test_an_unreachable_application_is_down(self, mock_head):
        mock_head.side_effect = self.script.requests.ConnectionError("refused")

        self._run_main(
            {"gone.example.org": _target([200], application_id="web-app-gone")}
        )

        self.assertEqual(
            self._status()["applications"]["web-app-gone"]["state"], "down"
        )

    @patch("requests.head")
    def test_a_stopped_marker_reports_paused_whatever_the_answer(self, mock_head):
        mock_head.side_effect = lambda url, **_: _Response(503)
        with tempfile.TemporaryDirectory() as instance:
            marker = Path(instance) / ".app-control-state"
            marker.write_text("stopped\n")
            self._run_main(
                {
                    "p.example.org": _target(
                        [200], paused_marker=str(marker), application_id="web-app-p"
                    )
                }
            )

        self.assertEqual(self._status()["applications"]["web-app-p"]["state"], "paused")

    @patch("requests.head")
    def test_an_application_takes_the_state_of_its_worst_domain(self, mock_head):
        codes = {"app.example.org": 200, "www.app.example.org": 404}
        mock_head.side_effect = lambda url, **_: _Response(
            codes[url.split("://", 1)[1]]
        )

        self._run_main(
            {
                "app.example.org": _target([200], application_id="web-app-x"),
                "www.app.example.org": _target([301], application_id="web-app-x"),
            }
        )

        self.assertEqual(
            self._status()["applications"]["web-app-x"]["state"], "degraded"
        )

    @patch("requests.head")
    def test_a_domain_without_an_application_stays_out_of_the_document(self, mock_head):
        mock_head.side_effect = lambda url, **_: _Response(200)

        self._run_main({"stray.example.org": _target([200])})

        status = self._status()
        self.assertEqual(status["applications"], {})
        self.assertTrue(status["generated"].endswith("+00:00"))

    @patch("requests.head")
    def test_a_paused_application_may_answer_with_the_paused_page(self, mock_head):
        mock_head.side_effect = lambda url, **_: _Response(503)
        with tempfile.TemporaryDirectory() as instance:
            marker = Path(instance) / ".app-control-state"
            marker.write_text("stopped\n")
            exit_code, output = self._run_main(
                {"paused.example.org": _target([200], paused_marker=str(marker))}
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("paused.example.org: OK", output)

    @patch("requests.head")
    def test_a_started_application_still_fails_on_503(self, mock_head):
        mock_head.side_effect = lambda url, **_: _Response(503)
        with tempfile.TemporaryDirectory() as instance:
            marker = Path(instance) / ".app-control-state"
            marker.write_text("started\n")
            exit_code, output = self._run_main(
                {"running.example.org": _target([200], paused_marker=str(marker))}
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("running.example.org: ERROR: Expected [200]. Got 503.", output)

    @patch("requests.head")
    def test_an_application_outside_app_control_fails_on_503(self, mock_head):
        mock_head.side_effect = lambda url, **_: _Response(503)
        exit_code, _ = self._run_main({"plain.example.org": _target([200])})
        self.assertEqual(exit_code, 1)

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

    @patch("requests.head")
    def test_output_stays_sorted_by_domain(self, mock_head):
        mock_head.side_effect = lambda url, **_: _Response(200)

        targets = {f"d{i:02d}.example.org": _target([200]) for i in reversed(range(40))}
        exit_code, output = self._run_main(targets)
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            output.splitlines(),
            [f"d{i:02d}.example.org: OK" for i in range(40)]
            + [
                f"{application_id}: NO TARGET: its dashboard badge reads unknown."
                for application_id in sorted(PUBLISHED)
            ],
        )

    @patch("requests.head")
    def test_verifies_against_the_trust_bundle(self, mock_head):
        mock_head.return_value = _Response(200)

        with (
            tempfile.NamedTemporaryFile(suffix=".crt") as bundle,
            patch.dict(os.environ, {"CA_TRUST_BUNDLE": bundle.name}),
        ):
            exit_code, _ = self._run_main({"a.example.org": _target([200])})

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_head.call_args.kwargs["verify"], bundle.name)

    @patch("requests.head")
    def test_missing_trust_bundle_fails(self, mock_head):
        mock_head.return_value = _Response(200)

        with patch.dict(os.environ, {"CA_TRUST_BUNDLE": "/nonexistent/ca-bundle.crt"}):
            exit_code, output = self._run_main({"a.example.org": _target([200])})

        self.assertEqual(exit_code, 1)
        self.assertIn("missing bundle: /nonexistent/ca-bundle.crt", output)

    def _run_main(self, targets):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = self.script.main(self._argv(json.dumps(targets), PUBLISHED))
        return exit_code, buffer.getvalue()

    def _status(self):
        return json.loads(read_text(str(self.status_file)))


if __name__ == "__main__":
    unittest.main()
