import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

sys.path.insert(
    0, str(PROJECT_ROOT / "roles/sys-ctl-hlth-github-settings/files/python")
)
import github_api

_spec = importlib.util.spec_from_file_location(
    "deployed_code_check",
    PROJECT_ROOT / "roles/sys-ctl-hlth-deployed-code/files/python/script.py",
)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

URL = "https://github.com/o/r.git"  # nocheck: url


def git(*args):
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class FakeApi:
    def __init__(self, unverified=(), failure=None, token="token"):  # noqa: S107 - a fake API client's placeholder token
        self.unverified = unverified
        self.failure = failure
        self.token = token
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if self.failure:
            raise script.CheckError(self.failure)
        sha = path.rsplit("/", 1)[-1]
        verified = sha not in self.unverified
        return {
            "commit": {
                "verification": {
                    "verified": verified,
                    "reason": "valid" if verified else "unsigned",
                }
            }
        }


class Repos:
    def __init__(self):
        root = Path(tempfile.mkdtemp())
        self.origin = root / "origin.git"
        self.checkout = str(root / "checkout")
        src = root / "src"
        git("init", "--quiet", "--bare", "--initial-branch=main", str(self.origin))
        git("init", "--quiet", "--initial-branch=main", str(src))
        (src / "a.txt").write_text("a\n", encoding="utf-8")
        (src / "b.txt").write_text("b\n", encoding="utf-8")
        git("-C", str(src), "add", ".")
        git("-C", str(src), "commit", "--quiet", "-m", "base")
        self.main = git("-C", str(src), "rev-parse", "HEAD")
        git("-C", str(src), "switch", "--quiet", "-c", "feature")
        (src / "a.txt").write_text("feature\n", encoding="utf-8")
        git("-C", str(src), "commit", "--quiet", "-am", "feature")
        self.feature = git("-C", str(src), "rev-parse", "HEAD")
        git("-C", str(src), "push", "--quiet", str(self.origin), "main", "feature")
        git("clone", "--quiet", str(self.origin), self.checkout)
        git("-C", self.checkout, "config", "remote.origin.url", URL)
        git("-C", self.checkout, "config", f"url.file://{self.origin}.insteadOf", URL)
        git("-C", self.checkout, "fetch", "--quiet", "origin", "feature")

    def checkout_commit(self, commit):
        git("-C", self.checkout, "checkout", "--quiet", "--detach", commit)


def kinds(events):
    return [(event["dc_kind"], event.get("dc_check")) for event in events]


class TestCheckout(unittest.TestCase):
    def setUp(self):
        self.repos = Repos()

    def check(self, api=None):
        return script.check_checkout(self.repos.checkout, api or FakeApi(), 30)

    def test_clean_verified_commit_on_main_has_no_finding(self):
        api = FakeApi()
        self.assertEqual(self.check(api), [])
        self.assertEqual(api.paths, [f"/repos/o/r/commits/{self.repos.main}"])

    def test_modified_tracked_file(self):
        Path(self.repos.checkout, "b.txt").write_text("tampered\n", encoding="utf-8")
        Path(self.repos.checkout, "untracked.txt").write_text(
            "ignored\n", encoding="utf-8"
        )
        events = self.check()
        self.assertEqual(kinds(events), [("modified", None)])
        self.assertEqual(
            (events[0]["dc_path"], events[0]["dc_status"], events[0]["dc_commit"]),
            ("b.txt", "M", self.repos.main),
        )

    def test_deleted_tracked_file(self):
        Path(self.repos.checkout, "b.txt").unlink()
        self.assertEqual(
            [(event["dc_path"], event["dc_status"]) for event in self.check()],
            [("b.txt", "D")],
        )

    def test_commit_not_on_default_branch(self):
        self.repos.checkout_commit(self.repos.feature)
        events = self.check()
        self.assertEqual(kinds(events), [("unmerged", None)])
        self.assertEqual(
            (events[0]["dc_commit"], events[0]["dc_branch"]),
            (self.repos.feature, "main"),
        )

    def test_unverified_commit(self):
        events = self.check(FakeApi(unverified=(self.repos.main,)))
        self.assertEqual(kinds(events), [("unverified", None)])
        self.assertEqual(events[0]["dc_reason"], "unsigned")

    def test_failed_api_is_an_error_not_ok(self):
        self.assertEqual(
            kinds(self.check(FakeApi(failure="HTTP 502: Server Error"))),
            [("error", "verification")],
        )

    def test_empty_token_is_an_error(self):
        events = self.check(FakeApi(token=""))
        self.assertEqual(kinds(events), [("error", "verification")])
        self.assertEqual(events[0]["dc_reason"], "the token file is empty")

    def test_unreachable_origin_is_a_fetch_error(self):
        git(
            "-C",
            self.repos.checkout,
            "config",
            f"url.file://{self.repos.origin}-gone.insteadOf",
            URL,
        )
        git(
            "-C",
            self.repos.checkout,
            "config",
            "--unset",
            f"url.file://{self.repos.origin}.insteadOf",
        )
        self.assertEqual(kinds(self.check()), [("error", "fetch")])

    def test_origin_not_on_github(self):
        git(
            "-C",
            self.repos.checkout,
            "config",
            "remote.origin.url",
            f"file://{self.repos.origin}",
        )
        events = self.check()
        self.assertEqual(kinds(events), [("error", "verification")])
        self.assertIn("is not a GitHub repository", events[0]["dc_reason"])

    def test_not_a_checkout(self):
        self.assertEqual(
            kinds(script.check_checkout(tempfile.mkdtemp(), FakeApi(), 30)),
            [("error", "checkout")],
        )
        self.assertEqual(
            kinds(script.check_checkout("/nonexistent/checkout", FakeApi(), 30)),
            [("error", "checkout")],
        )

    def test_modified_files_are_capped(self):
        for index in range(script.MAX_MODIFIED + 3):
            Path(self.repos.checkout, f"f{index}.txt").write_text(
                "x\n", encoding="utf-8"
            )
        git("-C", self.repos.checkout, "add", ".")
        events = self.check()
        self.assertEqual(len(events), script.MAX_MODIFIED + 1)
        self.assertEqual(events[-1]["dc_path"], "3 more files")

    def test_run_summary(self):
        self.repos.checkout_commit(self.repos.feature)
        events = script.run(
            [self.repos.checkout, "/nonexistent/checkout"], FakeApi(), 30
        )
        self.assertEqual(
            events[-1],
            {
                "dc_kind": "run",
                "dc_checkouts": "2",
                "dc_findings": "1",
                "dc_errors": "1",
            },
        )


class TestHelpers(unittest.TestCase):
    def test_parse_porcelain(self):
        output = " M a.txt\0D  b.txt\0R  new.txt\0old.txt\0M  c d.txt\0"
        self.assertEqual(
            script.parse_porcelain(output),
            [("M", "a.txt"), ("D", "b.txt"), ("R", "new.txt"), ("M", "c d.txt")],
        )

    def test_github_slug(self):
        for url in (
            "https://github.com/o/r.git",  # nocheck: url
            "https://github.com/o/r",  # nocheck: url
            "git@github.com:o/r.git",
            "ssh://git@github.com/o/r.git",
            "https://x-access-token:secret@github.com/o/r.git",  # nocheck: url
        ):
            self.assertEqual(script.github_slug(url), "o/r", url)
        for url in (
            "https://gitlab.example/o/r.git",
            "https://github.example/o/r.git",
            "file:///srv/r.git",
            "/srv/r.git",
        ):
            self.assertIsNone(script.github_slug(url), url)

    def test_credentials_are_redacted(self):
        self.assertEqual(
            script.clean(
                "fatal: unable to access 'https://user:secret@github.example/o/r.git/'"
            ),
            "fatal: unable to access 'https://***@github.example/o/r.git/'",
        )

    def test_uses_the_shared_github_client(self):
        self.assertIs(script.Api, github_api.Api)
        self.assertIs(script.CheckError, github_api.CheckError)


if __name__ == "__main__":
    unittest.main()
