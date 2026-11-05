import sys
import unittest

from utils import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/sys-ctl-hlth-git-settings/files/python"))
import git_gitea

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


if __name__ == "__main__":
    unittest.main()
