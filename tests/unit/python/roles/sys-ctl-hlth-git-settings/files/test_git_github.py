import sys
import unittest

from utils import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/sys-ctl-hlth-git-settings/files/python"))
import git_github


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


if __name__ == "__main__":
    unittest.main()
