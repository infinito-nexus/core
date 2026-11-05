import sys
import unittest

from utils import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/sys-ctl-hlth-git-settings/files/python"))
from git import gitlab as git_gitlab

API = "https://gitlab.example.org/api/v4"  # nocheck: url


class FakeApi:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, path, missing_ok=False):
        self.calls.append((path, missing_ok))
        return self.payload


class TestGitlab(unittest.TestCase):
    def test_verified_signature(self):
        api = FakeApi({"verification_status": "verified"})
        self.assertEqual(
            git_gitlab.commit_verification(api, "g/sub/r", "abc"), (True, "verified")
        )
        self.assertEqual(
            api.calls,
            [("/projects/g%2Fsub%2Fr/repository/commits/abc/signature", True)],
        )

    def test_missing_signature_is_unsigned_not_a_failure(self):
        self.assertEqual(
            git_gitlab.commit_verification(FakeApi(None), "g/r", "abc"),
            (False, "unsigned"),
        )

    def test_unverified_signature_keeps_the_status(self):
        api = FakeApi({"verification_status": "unverified"})
        self.assertEqual(
            git_gitlab.commit_verification(api, "g/r", "abc"), (False, "unverified")
        )

    def test_repository_keeps_subgroups(self):
        self.assertEqual(
            git_gitlab.repository("git@gitlab.example.org:g/sub/r.git", API), "g/sub/r"
        )

    def test_client_headers(self):
        self.assertEqual(
            git_gitlab.client(API, "tok", 5, "ua").headers["PRIVATE-TOKEN"], "tok"
        )


class TestGitlabSettings(unittest.TestCase):
    def test_protection_with_approval_settings(self):
        protection = git_gitlab.protection(
            {"allow_force_push": False, "code_owner_approval_required": True},
            {"approvals_before_merge": 2, "reset_approvals_on_push": True},
        )
        self.assertIs(protection["required_signatures"], git_gitlab.UNSUPPORTED)
        self.assertEqual(protection["required_approving_review_count"], 2)
        self.assertTrue(protection["require_code_owner_review"])
        self.assertTrue(protection["dismiss_stale_reviews"])
        self.assertTrue(protection["force_push_blocked"])
        self.assertTrue(protection["deletion_blocked"])

    def test_edition_without_approvals_reports_them_unsupported(self):
        protection = git_gitlab.protection(None, None)
        self.assertIs(
            protection["required_approving_review_count"], git_gitlab.UNSUPPORTED
        )
        self.assertIs(protection["dismiss_stale_reviews"], git_gitlab.UNSUPPORTED)
        self.assertFalse(protection["force_push_blocked"])

    def test_owners_are_access_level_50(self):
        class Members:
            def get_all(self, path):
                return [
                    {"username": "owner", "access_level": 50},
                    {"username": "dev", "access_level": 30},
                ]

        self.assertEqual(git_gitlab.owners(Members(), "g"), ["owner"])


class TestGitlabWebhook(unittest.TestCase):
    def signed(self, body, stamp, key=b"key"):
        import base64
        import hashlib
        import hmac

        digest = hmac.new(key, f"m1.{stamp}.".encode() + body, hashlib.sha256).digest()
        return {
            "webhook-id": "m1",
            "webhook-timestamp": str(stamp),
            "webhook-signature": "v1," + base64.b64encode(digest).decode(),
        }

    def test_signing_token_signature(self):
        import base64

        secret = "whsec_" + base64.b64encode(b"key").decode()
        self.assertIsNone(
            git_gitlab.webhook_verify(self.signed(b"{}", 1000), b"{}", secret, 1000)
        )
        self.assertEqual(
            git_gitlab.webhook_verify(
                self.signed(b"{}", 1000, b"other"), b"{}", secret, 1000
            ),
            "signature",
        )
        self.assertEqual(
            git_gitlab.webhook_verify(
                self.signed(b"{}", 1000), b"{}", secret, 1000 + 301
            ),
            "replay",
        )
        self.assertEqual(
            git_gitlab.webhook_verify({"X-Gitlab-Token": "plain"}, b"{}", secret, 1000),
            "unsigned",
        )

    def test_events_and_push_record(self):
        self.assertEqual(
            git_gitlab.webhook_event({"X-Gitlab-Event": "Push Hook"}, {}), "push"
        )
        record = git_gitlab.webhook_record(
            "push",
            {
                "ref": "refs/heads/main",
                "before": "0" * 40,
                "after": "b",
                "user_username": "u",
                "project": {"path_with_namespace": "g/r", "default_branch": "main"},
                "commits": [{"id": "b", "modified": [".gitlab-ci.yml"]}],
            },
        )
        self.assertEqual(
            (
                record["gh_repo"],
                record["gh_created"],
                record["gh_forced"],
                record["gh_workflow_paths"],
            ),
            ("g/r", "true", "unsupported", ".gitlab-ci.yml"),
        )

    def test_group_member_event_maps_to_organization(self):
        record = git_gitlab.webhook_record(
            "organization",
            {
                "event_name": "user_add_to_group",
                "group_path": "g",
                "user_username": "m",
                "group_access": "Owner",
            },
        )
        self.assertEqual(
            (record["gh_action"], record["gh_member"], record["gh_permission"]),
            ("member_added", "m", "owner"),
        )

    def test_merged_lookup_uses_merge_requests_of_the_commit(self):
        class Requests:
            def get_all(self, path):
                self.path = path
                return [{"state": "merged", "target_branch": "main"}]

        api = Requests()
        self.assertTrue(git_gitlab.merged_into(api, "g/r", "a", "main"))
        self.assertEqual(
            api.path, "/projects/g%2Fr/repository/commits/a/merge_requests"
        )


if __name__ == "__main__":
    unittest.main()
