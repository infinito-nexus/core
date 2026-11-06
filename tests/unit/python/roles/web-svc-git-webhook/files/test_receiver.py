import base64
import hashlib
import hmac
import http.client
import importlib
import importlib.util
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from utils import PROJECT_ROOT

SCRIPT_DIR = PROJECT_ROOT / "roles/web-svc-git-webhook/files/python"
PACKAGE_DIR = PROJECT_ROOT / "roles/sys-ctl-hlth-git-settings/files/python"
sys.path.insert(0, str(PACKAGE_DIR))
sys.path.insert(0, str(SCRIPT_DIR))
_spec = importlib.util.spec_from_file_location(
    "git_webhook_receiver", SCRIPT_DIR / "receiver.py"
)
receiver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(receiver)
github = importlib.import_module("git.github")
core = importlib.import_module("git.core")

SECRET = "test-secret"
SIGNING = "whsec_" + base64.b64encode(SECRET.encode()).decode()
REPO = {"full_name": "o/r", "default_branch": "main"}


def sign(body):
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def config(tmp, token=""):
    providers = {
        "/github": {
            "provider": "github",
            "secret": SECRET,
            "api_url": "https://api.invalid",
            "token": token,
        },
        "/gitea": {
            "provider": "gitea",
            "secret": SECRET,
            "api_url": "https://gitea.invalid/api/v1",
            "token": token,
        },
        "/gitlab": {
            "provider": "gitlab",
            "secret": SIGNING,
            "api_url": "https://gitlab.invalid/api/v4",
            "token": token,
        },
        "/unset": {"provider": "gitea", "secret": "", "api_url": "", "token": ""},
    }
    return {
        **receiver.load_config(
            {
                "WEBHOOK_PROVIDERS": json.dumps(providers),
                "WEBHOOK_PORT": "0",
                "WEBHOOK_MAX_BYTES": "1024",
                "WEBHOOK_STATE_DB": str(Path(tmp) / "state.sqlite"),
                "WEBHOOK_REPLAY_DAYS": "1",
                "WEBHOOK_API_TIMEOUT": "1",
                "WEBHOOK_PR_ATTEMPTS": "2",
                "WEBHOOK_PR_DELAY": "0",
            }
        ),
        "trusted_proxy": None,
    }


class TestConfig(unittest.TestCase):
    def test_only_providers_with_a_secret_are_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                sorted(config(tmp)["endpoints"]), ["/gitea", "/github", "/gitlab"]
            )

    def test_providers_that_do_not_decode_to_an_object_fail_at_start(self):
        double_encoded = json.dumps(json.dumps({"/github": {"secret": SECRET}}))
        with self.assertRaisesRegex(TypeError, "JSON object.*got a JSON str"):
            receiver.load_config(
                {"WEBHOOK_API_TIMEOUT": "1", "WEBHOOK_PROVIDERS": double_encoded}
            )

    def test_a_refused_api_url_fails_at_start(self):
        with self.assertRaises(ValueError):
            receiver.Endpoint(
                "/github",
                {"provider": "github", "secret": "s", "api_url": "file:///etc"},
                1,
            )

    def test_unsupported_fields_are_reported_once_per_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = []
            with mock.patch.object(receiver, "emit", lines.append):
                receiver.report_unsupported(config(tmp)["endpoints"])
        providers = {line["gh_provider"] for line in lines}
        self.assertEqual(providers, {"gitea", "gitlab"})
        self.assertIn(
            {
                "gh_kind": "unsupported",
                "gh_provider": "gitlab",
                "gh_field": "push.forced",
            },
            lines,
        )


class TestLoggedPath(unittest.TestCase):
    KNOWN = ("/", "/healthz", "/github")

    def test_known_paths_are_logged_whole(self):
        self.assertEqual(receiver.logged_path("/github?x=1", self.KNOWN), "/github")

    def test_single_segment_is_decoded_for_the_canary(self):
        self.assertEqual(
            receiver.logged_path("/canary%20app-run", self.KNOWN), "/canary app-run"
        )

    def test_deeper_segments_and_query_never_reach_the_log(self):
        self.assertEqual(
            receiver.logged_path("/password/reset/SECRET", self.KNOWN), "/password/..."
        )
        self.assertEqual(
            receiver.logged_path("/api/v1/home?access_token=SECRET", self.KNOWN),
            "/api/...",
        )


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


class TestDirectPush(unittest.TestCase):
    def run_check(self, payload, merged, token="token"):  # noqa: S107 - a fake endpoint's placeholder token
        endpoint = types.SimpleNamespace(adapter=github, api=object(), token=token)
        lines = []
        with (
            mock.patch.object(receiver, "emit", lines.append),
            mock.patch.object(github, "merged_into", merged),
        ):
            receiver.check_direct_push(
                {"pr_attempts": 2, "pr_delay": 0},
                endpoint,
                "d",
                "o/r",
                payload,
                sleep=lambda _: None,
            )
        self.assertEqual(len(lines), 1)
        return lines[0]

    def test_commits_from_a_merged_pull_request_are_ok(self):
        line = self.run_check({"commits": [{"id": "a"}], "after": "a"}, lambda *a: True)
        self.assertEqual((line["gh_result"], line["gh_provider"]), ("ok", "github"))

    def test_commit_without_pull_request_is_a_direct_push(self):
        merged = mock.Mock(return_value=False)
        line = self.run_check(
            {"commits": [{"id": "a"}], "after": "a", "repository": REPO}, merged
        )
        self.assertEqual(
            (line["gh_result"], line["gh_commits"], line["gh_repo"]),
            ("no_pr", "a", "o/r"),
        )
        self.assertEqual(merged.call_count, 2)

    def test_lookup_asks_for_the_repositorys_own_default_branch(self):
        merged = mock.Mock(return_value=True)
        repo = {"full_name": "o/legacy", "default_branch": "trunk"}
        line = self.run_check({"commits": [{"id": "a"}], "repository": repo}, merged)
        self.assertEqual(merged.call_args.args[-1], "trunk")
        self.assertEqual(line["gh_default_branch"], "trunk")

    def test_late_association_counts_as_merged(self):
        line = self.run_check(
            {"commits": [{"id": "a"}], "after": "a"},
            mock.Mock(side_effect=[False, True]),
        )
        self.assertEqual(line["gh_result"], "ok")

    def test_missing_token_is_an_error_not_a_pass(self):
        line = self.run_check({"commits": [{"id": "a"}]}, lambda *a: True, token="")
        self.assertEqual(
            (line["gh_result"], line["gh_reason"]), ("error", "no token configured")
        )

    def test_failed_lookup_is_an_error(self):
        def broken(*args):
            raise core.CheckError("HTTP 502")

        self.assertEqual(
            self.run_check({"commits": [{"id": "a"}]}, broken)["gh_result"], "error"
        )

    def test_too_many_commits_is_an_error(self):
        commits = [{"id": str(n)} for n in range(core.MAX_COMMITS + 1)]
        self.assertEqual(
            self.run_check({"commits": commits}, lambda *a: True)["gh_result"], "error"
        )


class TestHandler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name)
        self.lines = []
        self.patch = mock.patch.object(receiver, "emit", self.lines.append)
        self.patch.start()
        store = receiver.DeliveryStore(self.cfg["state_db"], self.cfg["keep_seconds"])
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), receiver.make_handler(self.cfg, store)
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.patch.stop()
        self.tmp.cleanup()

    def request(self, method, path, body=b"", headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=5
        )
        connection.request(method, path, body=body, headers=headers or {})
        status = connection.getresponse().status
        connection.close()
        return status

    def post(self, body, delivery="d1", signature=None, event="ping"):
        headers = {
            "X-GitHub-Delivery": delivery,
            "X-GitHub-Event": event,
            "Content-Type": "application/json",
        }
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
        self.assertEqual(
            [r["gh_reason"] for r in self.kinds("rejected")], ["unsigned", "signature"]
        )

    def test_oversized_body_is_refused(self):
        self.assertEqual(self.post(b"x" * 200000), 413)
        self.assertEqual(self.kinds("rejected")[0]["gh_reason"], "oversized")

    def test_head_and_get_answer_on_the_root(self):
        self.assertEqual(self.request("HEAD", "/"), 200)
        self.assertEqual(self.request("GET", "/"), 200)
        self.assertEqual(self.request("PUT", "/github"), 405)

    def test_provider_without_a_secret_is_not_served(self):
        self.assertEqual(
            self.request("POST", "/unset", b"{}", {"Content-Type": "application/json"}),
            404,
        )

    def test_access_line_carries_the_decoded_path(self):
        self.assertEqual(self.request("GET", "/canary%20app-run"), 404)
        self.assertEqual(
            self.kinds("access")[0]["gh_request"], "GET /canary app-run HTTP/1.1"
        )

    def test_gitea_delivery_is_verified_with_its_own_header(self):
        body = json.dumps({"ref": "refs/heads/feature", "repository": REPO}).encode()
        headers = {
            "X-Gitea-Event": "push",
            "X-Gitea-Delivery": "g1",
            "X-Gitea-Signature": hmac.new(
                SECRET.encode(), body, hashlib.sha256
            ).hexdigest(),
        }
        self.assertEqual(self.request("POST", "/gitea", body, headers), 202)
        self.assertEqual(
            self.request(
                "POST", "/gitea", body, {**headers, "X-Gitea-Signature": "00"}
            ),
            401,
        )
        delivery = self.kinds("delivery")[0]
        self.assertEqual(
            (delivery["gh_provider"], delivery["gh_forced"]), ("gitea", "unsupported")
        )

    def test_gitlab_delivery_needs_the_signing_token(self):
        body = json.dumps(
            {
                "object_kind": "push",
                "ref": "refs/heads/feature",
                "project": {"path_with_namespace": "g/r"},
            }
        ).encode()
        stamp = str(int(time.time()))
        key = base64.b64decode(SIGNING.removeprefix("whsec_"))
        signature = (
            "v1,"
            + base64.b64encode(
                hmac.new(key, f"w1.{stamp}.".encode() + body, hashlib.sha256).digest()
            ).decode()
        )
        headers = {
            "X-Gitlab-Event": "Push Hook",
            "webhook-id": "w1",
            "webhook-timestamp": stamp,
            "webhook-signature": signature,
        }
        self.assertEqual(self.request("POST", "/gitlab", body, headers), 202)
        plain = {
            "X-Gitlab-Event": "Push Hook",
            "webhook-id": "w2",
            "X-Gitlab-Token": SECRET,
        }
        self.assertEqual(self.request("POST", "/gitlab", body, plain), 401)
        self.assertEqual(self.kinds("delivery")[0]["gh_repo"], "g/r")
        self.assertEqual(self.kinds("rejected")[0]["gh_reason"], "unsigned")

    def test_x_real_ip_from_an_untrusted_peer_is_ignored(self):
        self.request("GET", "/", headers={"X-Real-IP": "203.0.113.9"})
        self.assertEqual(self.kinds("access")[0]["gh_srcip"], "127.0.0.1")

    def test_x_real_ip_from_the_front_proxy_is_logged(self):
        self.cfg["trusted_proxy"] = "127.0.0.1"
        self.request("GET", "/", headers={"X-Real-IP": "203.0.113.9"})
        self.assertEqual(self.kinds("access")[0]["gh_srcip"], "203.0.113.9")


class TestClientIp(unittest.TestCase):
    def test_trusted_proxy_passes_the_header_through(self):
        self.assertEqual(
            receiver.client_ip("192.168.82.1", "203.0.113.9", "192.168.82.1"),
            "203.0.113.9",
        )

    def test_any_other_peer_is_logged_as_itself(self):
        self.assertEqual(
            receiver.client_ip("10.0.0.7", "203.0.113.9", "192.168.82.1"), "10.0.0.7"
        )
        self.assertEqual(
            receiver.client_ip("10.0.0.7", "203.0.113.9", None), "10.0.0.7"
        )

    def test_missing_or_forged_header_falls_back_to_the_peer(self):
        self.assertEqual(
            receiver.client_ip("192.168.82.1", None, "192.168.82.1"), "192.168.82.1"
        )
        self.assertEqual(
            receiver.client_ip("192.168.82.1", "evil\nline", "192.168.82.1"),
            "192.168.82.1",
        )


class TestDefaultGateway(unittest.TestCase):
    def test_reads_the_default_route(self):
        table = (
            "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
            "eth0\t0052A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\n"
            "eth0\t00000000\t0152A8C0\t0003\t0\t0\t0\t00000000\n"
        )
        self.assertEqual(receiver.default_gateway(table), "192.168.82.1")

    def test_no_default_route(self):
        self.assertIsNone(receiver.default_gateway("Iface\tDestination\tGateway\n"))


if __name__ == "__main__":
    unittest.main()
