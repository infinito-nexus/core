import sys
import unittest

from utils import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/sys-ctl-hlth-git-settings/files/python"))
from git import github as git_github


class FakeApi:
    def __init__(self, payload):
        self.payload = payload
        self.paths = []

    def get(self, path, missing_ok=False):
        self.paths.append(path)
        return self.payload


class TestGithub(unittest.TestCase):
    def test_verified_commit(self):
        api = FakeApi(
            {"commit": {"verification": {"verified": True, "reason": "valid"}}}
        )
        self.assertEqual(
            git_github.commit_verification(api, "o/r", "abc"), (True, "valid")
        )
        self.assertEqual(api.paths, ["/repos/o/r/commits/abc"])

    def test_unverified_and_missing_verification(self):
        api = FakeApi(
            {"commit": {"verification": {"verified": False, "reason": "unsigned"}}}
        )
        self.assertEqual(
            git_github.commit_verification(api, "o/r", "abc"), (False, "unsigned")
        )
        self.assertEqual(
            git_github.commit_verification(FakeApi({}), "o/r", "abc"),
            (False, "no verification data"),
        )

    def test_repository_is_only_github_com(self):
        self.assertEqual(git_github.repository("git@github.com:o/r.git", ""), "o/r")
        self.assertIsNone(git_github.repository("git@gitlab.com:o/r.git", ""))

    def test_client_headers(self):
        api = git_github.client("https://api.github.com", "tok", 5, "ua")
        self.assertEqual(api.headers["Authorization"], "Bearer tok")
        self.assertEqual(api.headers["X-GitHub-Api-Version"], git_github.API_VERSION)


REPO = {"full_name": "o/r", "default_branch": "main"}


class TestGithubWebhook(unittest.TestCase):
    def test_signature(self):
        import hashlib
        import hmac

        body = b"{}"
        good = "sha256=" + hmac.new(b"s", body, hashlib.sha256).hexdigest()
        self.assertIsNone(
            git_github.webhook_verify({"X-Hub-Signature-256": good}, body, "s", 0)
        )
        self.assertEqual(git_github.webhook_verify({}, body, "s", 0), "unsigned")
        self.assertEqual(
            git_github.webhook_verify({"X-Hub-Signature-256": "sha1=ab"}, body, "s", 0),
            "signature",
        )

    def test_force_push_to_default_branch_with_workflow_change(self):
        record = git_github.webhook_record(
            "push",
            {
                "ref": "refs/heads/main",
                "forced": True,
                "deleted": False,
                "after": "b",
                "repository": REPO,
                "commits": [
                    {
                        "id": "b",
                        "modified": [".github/workflows/call-lint.yml", "README.md"],
                    }
                ],
            },
        )
        self.assertEqual(
            (
                record["gh_provider"],
                record["gh_on_default_branch"],
                record["gh_forced"],
                record["gh_workflow_paths"],
            ),
            ("github", "true", "true", ".github/workflows/call-lint.yml"),
        )

    def test_default_branch_comes_from_each_repository(self):
        repo = {"full_name": "o/legacy", "default_branch": "trunk"}
        self.assertEqual(
            git_github.webhook_record(
                "push", {"ref": "refs/heads/trunk", "repository": repo}
            )["gh_on_default_branch"],
            "true",
        )
        self.assertEqual(
            git_github.webhook_record(
                "push", {"ref": "refs/heads/main", "repository": repo}
            )["gh_on_default_branch"],
            "false",
        )
        self.assertEqual(
            git_github.webhook_record("push", {"ref": "refs/heads/"})[
                "gh_on_default_branch"
            ],
            "false",
        )

    def test_branch_and_tag_delete(self):
        branch = git_github.webhook_record(
            "delete", {"ref": "main", "ref_type": "branch", "repository": REPO}
        )
        tag = git_github.webhook_record(
            "delete", {"ref": "main", "ref_type": "tag", "repository": REPO}
        )
        self.assertEqual(
            (branch["gh_on_default_branch"], tag["gh_on_default_branch"]),
            ("true", "false"),
        )

    def test_member_deploy_key_and_alerts_keep_no_raw_payload(self):
        member = git_github.webhook_record(
            "member",
            {
                "action": "added",
                "member": {"login": "m"},
                "changes": {"permission": {"to": "admin"}},
                "repository": REPO,
            },
        )
        self.assertEqual((member["gh_member"], member["gh_permission"]), ("m", "admin"))
        key = git_github.webhook_record(
            "deploy_key", {"key": {"title": "k", "read_only": False}}
        )
        self.assertEqual(key["gh_key_read_only"], "false")
        alert = git_github.webhook_record(
            "secret_scanning_alert", {"alert": {"number": 3, "secret": "leaked"}}
        )
        self.assertNotIn("leaked", str(alert))
        dependabot = git_github.webhook_record(
            "dependabot_alert",
            {
                "alert": {
                    "security_advisory": {"severity": "HIGH"},
                    "dependency": {"package": {"name": "p"}},
                }
            },
        )
        self.assertEqual(
            (dependabot["gh_severity"], dependabot["gh_package"]), ("high", "p")
        )

    def test_pushed_commits_and_merged_lookup(self):
        self.assertEqual(
            git_github.pushed_commits(
                {"commits": [{"id": "a", "distinct": False}, {"id": "b"}]}
            ),
            ["b"],
        )
        self.assertEqual(
            git_github.pushed_commits({"commits": [], "after": "c"}), ["c"]
        )
        api = FakeApi([{"merged_at": "t", "base": {"ref": "main"}}])
        self.assertTrue(git_github.merged_into(api, "o/r", "a", "main"))
        self.assertEqual(api.paths, ["/repos/o/r/commits/a/pulls"])
        self.assertFalse(
            git_github.merged_into(
                FakeApi([{"merged_at": None, "base": {"ref": "main"}}]),
                "o/r",
                "a",
                "main",
            )
        )


if __name__ == "__main__":
    unittest.main()
