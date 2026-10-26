import hashlib
import hmac
import http.client
import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from utils import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "github_webhook_receiver", PROJECT_ROOT / "roles/web-svc-github-webhook/files/python/receiver.py"
)
receiver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(receiver)

SECRET = "test-secret"
REPO = {"full_name": "o/r", "default_branch": "main"}


def sign(body):
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def config(tmp, **overrides):
    values = {
        "secret": SECRET.encode(),
        "port": 0,
        "path": "/github",
        "max_bytes": 1024,
        "state_db": str(Path(tmp) / "state.sqlite"),
        "keep_seconds": 86400,
        "api_url": "http://api.invalid",
        "token": "token",
        "pr_attempts": 2,
        "pr_delay": 0,
    }
    values.update(overrides)
    return values


class TestSignature(unittest.TestCase):
    def test_valid_signature_passes(self):
        self.assertTrue(receiver.signature_valid(SECRET.encode(), b"{}", sign(b"{}")))

    def test_wrong_secret_fails(self):
        header = "sha256=" + hmac.new(b"other", b"{}", hashlib.sha256).hexdigest()
        self.assertFalse(receiver.signature_valid(SECRET.encode(), b"{}", header))

    def test_missing_or_sha1_header_fails(self):
        self.assertFalse(receiver.signature_valid(SECRET.encode(), b"{}", None))
        self.assertFalse(receiver.signature_valid(SECRET.encode(), b"{}", "sha1=abc"))


class TestLoggedPath(unittest.TestCase):
    KNOWN = ("/", "/healthz", "/github")

    def test_known_paths_are_logged_whole(self):
        self.assertEqual(receiver.logged_path("/github?x=1", self.KNOWN), "/github")

    def test_single_segment_is_decoded_for_the_canary(self):
        self.assertEqual(receiver.logged_path("/canary%20app-run", self.KNOWN), "/canary app-run")

    def test_deeper_segments_and_query_never_reach_the_log(self):
        self.assertEqual(receiver.logged_path("/password/reset/SECRET", self.KNOWN), "/password/...")
        self.assertEqual(receiver.logged_path("/api/v1/home?access_token=SECRET", self.KNOWN), "/api/...")


class TestDeliveryStore(unittest.TestCase):
    def test_second_delivery_with_same_id_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = receiver.DeliveryStore(str(Path(tmp) / "s.sqlite"), 100)
            self.assertTrue(store.first_time("a", 1000))
            self.assertFalse(store.first_time("a", 1001))

    def test_id_is_forgotten_after_the_keep_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = receiver.DeliveryStore(str(Path(tmp) / "s.sqlite"), 100)
            self.assertTrue(store.first_time("a", 1000))
            self.assertTrue(store.first_time("a", 1200))


class TestEventRecord(unittest.TestCase):
    def test_force_push_to_default_branch_with_workflow_change(self):
        payload = {
            "ref": "refs/heads/main",
            "forced": True,
            "deleted": False,
            "after": "b",
            "repository": REPO,
            "commits": [{"id": "b", "modified": [".github/workflows/call-lint.yml", "README.md"], "added": [], "removed": []}],
        }
        record = receiver.event_record("push", payload)
        self.assertEqual((record["gh_on_default_branch"], record["gh_default_branch"], record["gh_repo"]), ("true", "main", "o/r"))
        self.assertEqual(record["gh_forced"], "true")
        self.assertEqual(record["gh_workflow_paths"], ".github/workflows/call-lint.yml")

    def test_default_branch_comes_from_each_repository(self):
        repo = {"full_name": "o/legacy", "default_branch": "trunk"}
        on_trunk = receiver.event_record("push", {"ref": "refs/heads/trunk", "repository": repo})
        on_main = receiver.event_record("push", {"ref": "refs/heads/main", "repository": repo})
        self.assertEqual((on_trunk["gh_on_default_branch"], on_main["gh_on_default_branch"]), ("true", "false"))

    def test_push_to_other_branch_is_not_default(self):
        record = receiver.event_record("push", {"ref": "refs/heads/feature", "repository": REPO})
        self.assertEqual(record["gh_on_default_branch"], "false")

    def test_payload_without_repository_is_never_on_the_default_branch(self):
        record = receiver.event_record("push", {"ref": "refs/heads/"})
        self.assertEqual((record["gh_on_default_branch"], record["gh_default_branch"]), ("false", ""))

    def test_branch_delete_of_default_branch(self):
        record = receiver.event_record("delete", {"ref": "main", "ref_type": "branch", "repository": REPO})
        self.assertEqual((record["gh_on_default_branch"], record["gh_deleted"]), ("true", "true"))

    def test_tag_delete_is_not_default_branch(self):
        record = receiver.event_record("delete", {"ref": "main", "ref_type": "tag", "repository": REPO})
        self.assertEqual(record["gh_on_default_branch"], "false")

    def test_member_permission_and_deploy_key(self):
        member = receiver.event_record(
            "member", {"action": "added", "member": {"login": "m"}, "changes": {"permission": {"to": "admin"}}, "repository": REPO}
        )
        self.assertEqual((member["gh_member"], member["gh_permission"], member["gh_repo"]), ("m", "admin", "o/r"))
        key = receiver.event_record("deploy_key", {"action": "created", "key": {"title": "k", "read_only": False}})
        self.assertEqual(key["gh_key_read_only"], "false")

    def test_alerts_keep_no_secret_or_raw_payload(self):
        payload = {"action": "created", "alert": {"number": 3, "secret_type": "t", "secret": "leaked", "html_url": "u"}}
        record = receiver.event_record("secret_scanning_alert", payload)
        self.assertNotIn("leaked", json.dumps(record))
        dependabot = receiver.event_record(
            "dependabot_alert",
            {"action": "created", "alert": {"security_advisory": {"severity": "HIGH"}, "dependency": {"package": {"name": "p"}}}},
        )
        self.assertEqual((dependabot["gh_severity"], dependabot["gh_package"]), ("high", "p"))


class TestDirectPush(unittest.TestCase):
    def run_check(self, cfg, payload, merged):
        lines = []
        with mock.patch.object(receiver, "emit", lines.append), mock.patch.object(receiver, "merged_into", merged):
            receiver.check_direct_push(cfg, "d", "o/r", payload, sleep=lambda _: None)
        self.assertEqual(len(lines), 1)
        return lines[0]

    def test_commits_from_a_merged_pull_request_are_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = self.run_check(config(tmp), {"commits": [{"id": "a"}], "after": "a"}, lambda *a: True)
        self.assertEqual(line["gh_result"], "ok")

    def test_commit_without_pull_request_is_a_direct_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            merged = mock.Mock(return_value=False)
            line = self.run_check(config(tmp), {"commits": [{"id": "a"}], "after": "a", "repository": REPO}, merged)
        self.assertEqual((line["gh_result"], line["gh_commits"], line["gh_repo"]), ("no_pr", "a", "o/r"))
        self.assertEqual(merged.call_count, 2)

    def test_lookup_asks_for_the_repositorys_own_default_branch(self):
        repo = {"full_name": "o/legacy", "default_branch": "trunk"}
        with tempfile.TemporaryDirectory() as tmp:
            merged = mock.Mock(return_value=True)
            line = self.run_check(config(tmp), {"commits": [{"id": "a"}], "repository": repo}, merged)
        self.assertEqual(merged.call_args.args[-1], "trunk")
        self.assertEqual(line["gh_default_branch"], "trunk")

    def test_late_association_counts_as_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            merged = mock.Mock(side_effect=[False, True])
            line = self.run_check(config(tmp), {"commits": [{"id": "a"}], "after": "a"}, merged)
        self.assertEqual(line["gh_result"], "ok")

    def test_missing_token_is_an_error_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = self.run_check(config(tmp, token=""), {"commits": [{"id": "a"}]}, lambda *a: True)
        self.assertEqual((line["gh_result"], line["gh_reason"]), ("error", "no token configured"))

    def test_failed_lookup_is_an_error(self):
        def broken(*args):
            raise OSError("down")

        with tempfile.TemporaryDirectory() as tmp:
            line = self.run_check(config(tmp), {"commits": [{"id": "a"}]}, broken)
        self.assertEqual(line["gh_result"], "error")

    def test_too_many_commits_is_an_error(self):
        commits = [{"id": str(n)} for n in range(receiver.MAX_COMMITS + 1)]
        with tempfile.TemporaryDirectory() as tmp:
            line = self.run_check(config(tmp), {"commits": commits}, lambda *a: True)
        self.assertEqual(line["gh_result"], "error")

    def test_only_distinct_commits_are_checked(self):
        self.assertEqual(receiver.pushed_commits({"commits": [{"id": "a", "distinct": False}, {"id": "b"}]}), ["b"])


class TestHandler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name, token="")
        self.lines = []
        self.patch = mock.patch.object(receiver, "emit", self.lines.append)
        self.patch.start()
        store = receiver.DeliveryStore(self.cfg["state_db"], self.cfg["keep_seconds"])
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), receiver.make_handler(self.cfg, store))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.patch.stop()
        self.tmp.cleanup()

    def request(self, method, path, body=b"", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        status = connection.getresponse().status
        connection.close()
        return status

    def post(self, body, delivery="d1", signature=None, event="ping"):
        headers = {"X-GitHub-Delivery": delivery, "X-GitHub-Event": event, "Content-Type": "application/json"}
        if signature is not False:
            headers["X-Hub-Signature-256"] = signature or sign(body)
        return self.request("POST", "/github", body, headers)

    def kinds(self, kind):
        return [line for line in self.lines if line["gh_kind"] == kind]

    def test_signed_delivery_is_accepted_once(self):
        body = json.dumps({"zen": "z"}).encode()
        self.assertEqual(self.post(body), 202)
        self.assertEqual(self.post(body), 409)
        self.assertEqual(self.kinds("delivery")[0]["gh_event"], "ping")
        self.assertEqual(self.kinds("rejected")[0]["gh_reason"], "replay")

    def test_unsigned_and_wrong_signature_are_refused(self):
        self.assertEqual(self.post(b"{}", signature=False), 401)
        self.assertEqual(self.post(b"{}", delivery="d2", signature="sha256=00"), 401)
        self.assertEqual([r["gh_reason"] for r in self.kinds("rejected")], ["unsigned", "signature"])

    def test_oversized_body_is_refused(self):
        self.assertEqual(self.post(b"x" * 200000), 413)
        self.assertEqual(self.kinds("rejected")[0]["gh_reason"], "oversized")

    def test_head_and_get_answer_on_the_root(self):
        self.assertEqual(self.request("HEAD", "/"), 200)
        self.assertEqual(self.request("GET", "/"), 200)
        self.assertEqual(self.request("PUT", "/github"), 405)

    def test_access_line_carries_the_decoded_path(self):
        self.assertEqual(self.request("GET", "/canary%20app-run"), 404)
        self.assertEqual(self.kinds("access")[0]["gh_request"], "GET /canary app-run HTTP/1.1")

    def test_signature_failure_is_not_recorded_as_a_delivery(self):
        body = json.dumps({"zen": "z"}).encode()
        self.assertEqual(self.post(body, signature="sha256=00"), 401)
        self.assertEqual(self.post(body), 202)


if __name__ == "__main__":
    unittest.main()
