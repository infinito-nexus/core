import sys
import unittest

from utils import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/sys-ctl-hlth-git-settings/files/python"))
import git_gitlab

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


if __name__ == "__main__":
    unittest.main()
