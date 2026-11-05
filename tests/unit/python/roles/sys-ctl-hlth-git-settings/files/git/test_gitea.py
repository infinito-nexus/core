import sys
import unittest

from utils import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/sys-ctl-hlth-git-settings/files/python"))
from git import gitea as git_gitea

API = "https://git.example.org/api/v1"  # nocheck: url


class FakeApi:
    def __init__(self, payload):
        self.payload = payload
        self.paths = []

    def get(self, path, missing_ok=False):
        self.paths.append(path)
        return self.payload


class TestGitea(unittest.TestCase):
    def test_verified_commit_uses_the_git_commits_endpoint(self):
        api = FakeApi({"commit": {"verification": {"verified": True, "reason": ""}}})
        self.assertEqual(git_gitea.commit_verification(api, "o/r", "abc")[0], True)
        self.assertEqual(api.paths, ["/repos/o/r/git/commits/abc"])

    def test_unverified_commit_keeps_the_reason(self):
        api = FakeApi(
            {
                "commit": {
                    "verification": {
                        "verified": False,
                        "reason": "gpg.error.not_signed_commit",
                    }
                }
            }
        )
        self.assertEqual(
            git_gitea.commit_verification(api, "o/r", "abc"),
            (False, "gpg.error.not_signed_commit"),
        )

    def test_repository_follows_the_api_host(self):
        remote = "https://git.example.org/o/r.git"  # nocheck: url
        self.assertEqual(git_gitea.repository(remote, API), "o/r")
        self.assertIsNone(git_gitea.repository("git@github.com:o/r.git", API))

    def test_client_headers(self):
        self.assertEqual(
            git_gitea.client(API, "tok", 5, "ua").headers["Authorization"], "token tok"
        )


class TestGiteaSettings(unittest.TestCase):
    def test_protection_maps_to_the_shared_fields(self):
        rules = [
            {
                "rule_name": "main",
                "require_signed_commits": True,
                "required_approvals": 2,
                "dismiss_stale_approvals": True,
                "enable_force_push": False,
            }
        ]
        protection = git_gitea.protection(rules, "main")
        self.assertIs(protection["require_code_owner_review"], git_gitea.UNSUPPORTED)
        self.assertEqual(
            {k: v for k, v in protection.items() if v is not git_gitea.UNSUPPORTED},
            {
                "required_signatures": True,
                "required_approving_review_count": 2,
                "dismiss_stale_reviews": True,
                "force_push_blocked": True,
                "deletion_blocked": True,
            },
        )

    def test_unprotected_branch_blocks_nothing(self):
        protection = git_gitea.protection([{"rule_name": "other"}], "main")
        self.assertFalse(protection["force_push_blocked"])
        self.assertFalse(protection["deletion_blocked"])

    def test_missing_owners_team_is_a_failed_check(self):
        class Teams:
            def get_all(self, path):
                return [{"id": 1, "name": "Developers"}]

        with self.assertRaises(git_gitea.CheckError):
            git_gitea.owners(Teams(), "o")

    def test_settings_gitea_lacks_are_unsupported(self):
        collectors = git_gitea.collectors(FakeApi({}), "o/r", "main")
        for key in ("actions", "open_secret_scanning_alerts", "open_dependabot_alerts"):
            self.assertIs(collectors[key], git_gitea.UNSUPPORTED, key)


class TestGiteaWebhook(unittest.TestCase):
    def test_signature_is_plain_hex(self):
        import hashlib
        import hmac

        body = b"{}"
        good = hmac.new(b"s", body, hashlib.sha256).hexdigest()
        self.assertIsNone(
            git_gitea.webhook_verify({"X-Gitea-Signature": good}, body, "s", 0)
        )
        self.assertEqual(
            git_gitea.webhook_verify({"X-Gitea-Signature": ""}, body, "s", 0),
            "unsigned",
        )
        self.assertEqual(
            git_gitea.webhook_verify(
                {"X-Gitea-Signature": "sha256=" + good}, body, "s", 0
            ),
            "signature",
        )

    def test_push_record_marks_force_push_unsupported(self):
        record = git_gitea.webhook_record(
            "push",
            {
                "ref": "refs/heads/main",
                "before": "a" * 40,
                "after": "0" * 40,
                "repository": {"full_name": "o/r", "default_branch": "main"},
                "sender": {"login": "u"},
                "commits": [{"id": "b", "modified": [".gitea/workflows/ci.yml"]}],
            },
        )
        self.assertEqual(
            (
                record["gh_provider"],
                record["gh_forced"],
                record["gh_deleted"],
                record["gh_on_default_branch"],
                record["gh_workflow_paths"],
            ),
            ("gitea", "unsupported", "true", "true", ".gitea/workflows/ci.yml"),
        )
        self.assertIn("push.forced", git_gitea.UNSUPPORTED_WEBHOOK_FIELDS)

    def test_merged_lookup_uses_the_commit_pull_endpoint(self):
        api = FakeApi({"merged": True, "base": {"ref": "main"}})
        self.assertTrue(git_gitea.merged_into(api, "o/r", "a", "main"))
        self.assertEqual(api.paths, ["/repos/o/r/commits/a/pull"])
        self.assertFalse(git_gitea.merged_into(FakeApi(None), "o/r", "a", "main"))


if __name__ == "__main__":
    unittest.main()
