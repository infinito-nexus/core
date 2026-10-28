import importlib.util
import unittest

from utils import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "github_events",
    PROJECT_ROOT / "roles/web-svc-github-webhook/files/python/github_events.py",
)
github_events = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(github_events)


class TestHelpers(unittest.TestCase):
    def test_flag(self):
        self.assertEqual(
            (github_events.flag(1), github_events.flag(None)), ("true", "false")
        )

    def test_workflow_paths_are_unique_and_sorted(self):
        payload = {
            "commits": [
                {
                    "added": [".github/workflows/call-lint.yml"],
                    "modified": ["README.md"],
                },
                {
                    "removed": [
                        ".github/workflows/call-validation.yml",
                        ".github/workflows/call-lint.yml",
                    ]
                },
            ]
        }
        self.assertEqual(
            github_events.workflow_paths(payload),
            ".github/workflows/call-lint.yml,.github/workflows/call-validation.yml",
        )

    def test_default_branch(self):
        self.assertEqual(
            github_events.default_branch({"repository": {"default_branch": "trunk"}}),
            "trunk",
        )
        self.assertEqual(github_events.default_branch({}), "")

    def test_pushed_commits(self):
        self.assertEqual(
            github_events.pushed_commits(
                {"commits": [{"id": "a"}, {"id": "b", "distinct": False}]}
            ),
            ["a"],
        )
        self.assertEqual(
            github_events.pushed_commits({"commits": [], "after": "c"}), ["c"]
        )
        many = {
            "commits": [{"id": str(n)} for n in range(github_events.MAX_COMMITS + 1)]
        }
        self.assertIsNone(github_events.pushed_commits(many))

    def test_event_record_reports_a_push_to_the_default_branch(self):
        record = github_events.event_record(
            "push",
            {
                "ref": "refs/heads/main",
                "forced": True,
                "repository": {"full_name": "o/r", "default_branch": "main"},
            },
        )
        self.assertEqual(
            (record["gh_on_default_branch"], record["gh_forced"], record["gh_repo"]),
            ("true", "true", "o/r"),
        )


if __name__ == "__main__":
    unittest.main()
