import base64
import contextlib
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

_spec = importlib.util.spec_from_file_location(
    "github_settings_check", PROJECT_ROOT / "roles/sys-ctl-hlth-github-settings/files/python/script.py"
)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

SCOPE = "o/r"
EXPECTED = {
    "organization": "o",
    "owners": ["alice"],
    "repositories": {
        "r": {
            "branch_protection": {
                "required_signatures": True,
                "required_approving_review_count": 2,
                "require_code_owner_review": True,
                "dismiss_stale_reviews": True,
                "force_push_blocked": True,
                "deletion_blocked": True,
            },
            "collaborators": {"bob": "write"},
            "deploy_keys": [{"id": 7, "title": "deploy", "read_only": True}],
            "actions": {"enabled": True, "default_workflow_permissions": "read"},
            "pull_request_target": [".github/workflows/entry-cancel-superseded.yml"],
            "open_secret_scanning_alerts": 0,
            "open_dependabot_alerts": 0,
        }
    },
}
RULES = [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_signatures"},
    {"type": "pull_request", "parameters": {"required_approving_review_count": 2, "require_code_owner_review": True, "dismiss_stale_reviews_on_push": True}},
]


def parse_yaml(text):
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as handle:
        handle.write(text)
    try:
        return load_yaml_any(handle.name)
    finally:
        Path(handle.name).unlink()


def content(text):
    return {"content": base64.b64encode(text.encode()).decode()}


def responses(**overrides):
    values = {
        "/orgs/o/members?role=admin&per_page=100": [{"login": "alice"}],
        "/repos/o/r": {"default_branch": "main"},
        "/repos/o/r/branches/main/protection": None,
        "/repos/o/r/rules/branches/main?per_page=100": RULES,
        "/repos/o/r/collaborators?affiliation=direct&per_page=100": [{"login": "bob", "role_name": "write"}],
        "/repos/o/r/keys?per_page=100": [{"id": 7, "title": "deploy", "read_only": True}],
        "/repos/o/r/actions/permissions": {"enabled": True, "allowed_actions": "all"},
        "/repos/o/r/actions/permissions/workflow": {"default_workflow_permissions": "read"},
        "/repos/o/r/contents/.github/workflows?ref=main": [
            {"type": "file", "name": "entry-cancel-superseded.yml", "path": ".github/workflows/entry-cancel-superseded.yml"},
            {"type": "file", "name": "README.md", "path": ".github/workflows/README.md"},
        ],
        "/repos/o/r/contents/.github/workflows/entry-cancel-superseded.yml?ref=main": content("on:\n  pull_request_target:\n"),
        "/repos/o/r/secret-scanning/alerts?state=open&per_page=100": [],
        "/repos/o/r/dependabot/alerts?state=open&per_page=100": [],
    }
    values.update(overrides)
    return values


class FakeApi:
    token = "token"

    def __init__(self, values):
        self.values = values

    def _value(self, path):
        value = self.values[path]
        if isinstance(value, script.CheckError):
            raise value
        return value

    def get(self, path, missing_ok=False):
        return self._value(path)

    def get_all(self, path):
        return self._value(path)


def findings(values):
    return [event for event in script.run(FakeApi(values), EXPECTED) if event["gs_kind"] != "run"]


class TestDrift(unittest.TestCase):
    def test_one_event_per_differing_field(self):
        events = script.drift(SCOPE, "actions", {"enabled": True, "x": "a"}, {"enabled": False, "x": "a", "y": "b"})
        self.assertEqual(
            events,
            [{"gs_kind": "drift", "gs_scope": SCOPE, "gs_check": "actions", "gs_field": "enabled", "gs_expected": "true", "gs_actual": "false"}],
        )

    def test_extra_reports_added_and_removed_fields(self):
        events = script.drift(SCOPE, "collaborators", {"bob": "write"}, {"mallory": "admin"}, extra=True)
        self.assertEqual(
            [(event["gs_field"], event["gs_expected"], event["gs_actual"]) for event in events],
            [("bob", "write", "absent"), ("mallory", "absent", "admin")],
        )

    def test_values_are_truncated(self):
        events = script.drift(SCOPE, "c", {"f": "a"}, {"f": "x" * 1000})
        self.assertEqual(len(events[0]["gs_actual"]), script.MAX_VALUE)


class TestProtection(unittest.TestCase):
    def test_rulesets_alone(self):
        self.assertEqual(script.effective_protection(None, RULES), EXPECTED["repositories"]["r"]["branch_protection"])

    def test_no_protection_at_all(self):
        self.assertEqual(
            script.effective_protection(None, []),
            {
                "required_signatures": False,
                "required_approving_review_count": 0,
                "require_code_owner_review": False,
                "dismiss_stale_reviews": False,
                "force_push_blocked": False,
                "deletion_blocked": False,
            },
        )

    def test_classic_protection(self):
        classic = {
            "required_signatures": {"enabled": True},
            "required_pull_request_reviews": {"required_approving_review_count": 1, "require_code_owner_reviews": True},
            "allow_force_pushes": {"enabled": True},
            "allow_deletions": {"enabled": False},
        }
        protection = script.effective_protection(classic, [])
        self.assertTrue(protection["required_signatures"])
        self.assertEqual(protection["required_approving_review_count"], 1)
        self.assertFalse(protection["force_push_blocked"])
        self.assertTrue(protection["deletion_blocked"])

    def test_stricter_of_both_counts(self):
        classic = {"required_pull_request_reviews": {"required_approving_review_count": 3}}
        self.assertEqual(script.effective_protection(classic, RULES)["required_approving_review_count"], 3)


class TestPullRequestTarget(unittest.TestCase):
    def test_triggers(self):
        for workflow in (
            "on:\n  pull_request_target:\n    types: [opened]\n",
            "on:\n  - push\n  - pull_request_target\n",
            "on: [push, pull_request_target]\n",
            "'on': pull_request_target\n",
        ):
            self.assertTrue(script.uses_pull_request_target(workflow), workflow)

    def test_mentions_are_not_triggers(self):
        for workflow in (
            "on:\n  pull_request:\n# pull_request_target:\n",
            "jobs:\n  a:\n    if: ${{ github.event_name == 'pull_request_target' }}\n",
            "env:\n  TARGET_EVENT: pull_request_target\n",
        ):
            self.assertFalse(script.uses_pull_request_target(workflow), workflow)


class TestRun(unittest.TestCase):
    def test_matching_state_has_no_findings(self):
        events = script.run(FakeApi(responses()), EXPECTED)
        self.assertEqual(events, [{"gs_kind": "run", "gs_scope": "o", "gs_drift": "0", "gs_errors": "0"}])

    def test_every_drift_is_reported(self):
        events = findings(
            responses(
                **{
                    "/orgs/o/members?role=admin&per_page=100": [{"login": "alice"}, {"login": "mallory"}],
                    "/repos/o/r/rules/branches/main?per_page=100": RULES[:2],
                    "/repos/o/r/collaborators?affiliation=direct&per_page=100": [{"login": "bob", "role_name": "admin"}],
                    "/repos/o/r/keys?per_page=100": [{"id": 8, "title": "deploy", "read_only": False}],
                    "/repos/o/r/actions/permissions/workflow": {"default_workflow_permissions": "write"},
                    "/repos/o/r/contents/.github/workflows?ref=main": [
                        {"type": "file", "name": "entry-cancel-superseded.yml", "path": ".github/workflows/entry-cancel-superseded.yml"},
                        {"type": "file", "name": "call-lint.yml", "path": ".github/workflows/call-lint.yml"},
                    ],
                    "/repos/o/r/contents/.github/workflows/call-lint.yml?ref=main": content("on: pull_request_target\n"),
                    "/repos/o/r/secret-scanning/alerts?state=open&per_page=100": [{"number": 1}],
                    "/repos/o/r/dependabot/alerts?state=open&per_page=100": [{"number": 1}, {"number": 2}],
                }
            )
        )
        self.assertEqual(
            sorted((event["gs_check"], event["gs_field"], event["gs_actual"]) for event in events),
            sorted(
                [
                    ("owners", "mallory", "owner"),
                    ("branch_protection", "required_signatures", "false"),
                    ("branch_protection", "required_approving_review_count", "0"),
                    ("branch_protection", "require_code_owner_review", "false"),
                    ("branch_protection", "dismiss_stale_reviews", "false"),
                    ("collaborators", "bob", "admin"),
                    ("deploy_keys", "7", "absent"),
                    ("deploy_keys", "8", "deploy (read-write)"),
                    ("actions", "default_workflow_permissions", "write"),
                    ("pull_request_target", ".github/workflows/call-lint.yml", "present"),
                    ("secret_scanning", "open_alerts", "1"),
                    ("dependabot", "open_alerts", "2"),
                ]
            ),
        )

    def test_failed_check_is_an_error_not_no_drift(self):
        events = script.run(
            FakeApi(responses(**{"/repos/o/r/collaborators?affiliation=direct&per_page=100": script.CheckError("HTTP 403: rate limit exceeded")})),
            EXPECTED,
        )
        self.assertIn(
            {"gs_kind": "error", "gs_scope": SCOPE, "gs_check": "collaborators", "gs_reason": "HTTP 403: rate limit exceeded"}, events
        )
        self.assertEqual(events[-1], {"gs_kind": "run", "gs_scope": "o", "gs_drift": "0", "gs_errors": "1"})

    def test_unreachable_repository_is_one_error(self):
        events = findings(responses(**{"/repos/o/r": script.CheckError("HTTP 401: Bad credentials")}))
        self.assertEqual(events, [{"gs_kind": "error", "gs_scope": SCOPE, "gs_check": "repository", "gs_reason": "HTTP 401: Bad credentials"}])

    def test_empty_token(self):
        api = FakeApi({})
        api.token = ""
        self.assertEqual(script.run(api, EXPECTED)[0]["gs_check"], "token")


class StubApi:
    def __init__(self, values):
        def handler(*args):
            return _StubHandler(values, *args)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class _StubHandler(BaseHTTPRequestHandler):
    def __init__(self, values, *args):
        self.values = values
        super().__init__(*args)

    def do_GET(self):
        value = self.values.get(self.path, script.CheckError("missing"))
        status, payload = (404, {"message": "Not Found"}) if value is None or isinstance(value, script.CheckError) else (200, value)
        if isinstance(value, script.CheckError) and str(value) == "rate limit":
            status, payload = 403, {"message": "API rate limit exceeded"}
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestPrintCurrent(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "token").write_text("token\n", encoding="utf-8")
        (self.tmp / "expected.json").write_text(json.dumps(EXPECTED), encoding="utf-8")

    def print_current(self, values):
        stub = StubApi(values)
        self.addCleanup(stub.close)
        argv = ["script", "--api-url", stub.url, "--token-file", str(self.tmp / "token"), "--expected", str(self.tmp / "expected.json"),
                "--timeout", "5", "--print-current"]
        out = io.StringIO()
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(out):
            script.main()
        return out.getvalue()

    def test_prints_the_current_state_as_expected_file_yaml(self):
        printed = self.print_current(responses())
        self.assertTrue(printed.startswith("---\n"))
        state = parse_yaml(printed)
        repo = state["repositories"]["r"]
        self.assertEqual(state["organization"], "o")
        self.assertEqual(state["owners"], ["alice"])
        self.assertEqual(repo["branch_protection"], EXPECTED["repositories"]["r"]["branch_protection"])
        self.assertEqual(repo["deploy_keys"], [{"id": 7, "title": "deploy", "read_only": True}])
        self.assertEqual(repo["actions"], {"enabled": True, "allowed_actions": "all", "default_workflow_permissions": "read"})
        self.assertEqual(repo["pull_request_target"], [".github/workflows/entry-cancel-superseded.yml"])
        self.assertEqual(repo["open_dependabot_alerts"], 0)

    def test_printed_state_has_no_drift_against_itself(self):
        values = responses(**{"/repos/o/r/collaborators?affiliation=direct&per_page=100": []})
        state = parse_yaml(self.print_current(values))
        self.assertEqual(state["repositories"]["r"]["collaborators"], {})
        self.assertEqual(script.run(FakeApi(values), state), [{"gs_kind": "run", "gs_scope": "o", "gs_drift": "0", "gs_errors": "0"}])

    def test_failed_read_prints_nothing_and_exits(self):
        with self.assertRaises(SystemExit) as raised:
            self.print_current(responses(**{"/repos/o/r/collaborators?affiliation=direct&per_page=100": script.CheckError("rate limit")}))
        self.assertIn("o/r collaborators: HTTP 403: rate limit exceeded", str(raised.exception))

    def test_tag_required_without_print_current(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            script.parse_args(["--api-url", "u", "--token-file", "t", "--expected", "e", "--timeout", "1"])


class TestYaml(unittest.TestCase):
    def test_round_trip_quotes_what_yaml_would_reinterpret(self):
        value = {"a": ["dependabot[bot]", "123", "true", "on", ".github/workflows/call-lint.yml", "plain"], "b": {}, "c": [], "d": 0, "e": False,
                 "f": [{"id": 1, "title": "k: v"}], "1": "x"}
        self.assertEqual(parse_yaml("\n".join(script.to_yaml(value))), value)


class TestFailureReason(unittest.TestCase):
    def test_rate_limit(self):
        reason = script.failure_reason(403, json.dumps({"message": "API rate limit exceeded"}).encode(), {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "42"})
        self.assertEqual(reason, "HTTP 403: rate limit exceeded, resets at epoch 42")

    def test_secondary_rate_limit(self):
        self.assertIn("rate limit", script.failure_reason(429, b"", {}))

    def test_permission(self):
        reason = script.failure_reason(403, json.dumps({"message": "Resource not accessible by personal access token"}).encode(), {"X-RateLimit-Remaining": "4999"})
        self.assertEqual(reason, "HTTP 403: Resource not accessible by personal access token")


if __name__ == "__main__":
    unittest.main()
