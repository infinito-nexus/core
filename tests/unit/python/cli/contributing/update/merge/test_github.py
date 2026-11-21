from __future__ import annotations

import io
import json
import unittest
import zipfile
from unittest import mock

from cli.contributing.update.merge import github

REPO = "infinito-nexus/core"
SHA = "b" * 40


def lines(*objects):
    return "\n".join(json.dumps(item) for item in objects).encode()


def archive(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        for name, data in members.items():
            zipped.writestr(name, data)
    return buffer.getvalue()


class TestReads(unittest.TestCase):
    def test_items_paginates_and_parses_one_object_per_line(self):
        gh = mock.Mock(return_value=lines({"a": 1}, {"a": 2}) + b"\n")
        self.assertEqual(github.items(gh, "repos/x", ".[]"), [{"a": 1}, {"a": 2}])
        gh.assert_called_once_with(["api", "--paginate", "repos/x", "--jq", ".[]"])

    def test_open_pull_requests_drop_closed_ones_and_other_heads(self):
        prs = [
            {"number": 1, "state": "open", "head": {"sha": SHA}},
            {"number": 2, "state": "closed", "head": {"sha": SHA}},
            {"number": 3, "state": "open", "head": {"sha": "c" * 40}},
        ]
        gh = mock.Mock(return_value=lines(*prs))
        found = github.open_pull_requests(gh, REPO, SHA)
        self.assertEqual([pr["number"] for pr in found], [1])

    def test_changed_paths_keep_the_old_name_of_a_rename(self):
        files = [
            {
                "filename": "roles/web-app-new/meta/main.yml",
                "previous_filename": "roles/web-app-old/meta/main.yml",
            },
            {"filename": "pyproject.toml", "previous_filename": None},
        ]
        gh = mock.Mock(return_value=lines(*files))
        self.assertEqual(
            github.changed_paths(gh, REPO, 5),
            [
                "roles/web-app-new/meta/main.yml",
                "roles/web-app-old/meta/main.yml",
                "pyproject.toml",
            ],
        )


class TestCsvMembers(unittest.TestCase):
    def test_only_csv_members_are_read(self):
        blob = archive({"a.csv": "role\nx\n", "notes.txt": "role\ny\n"})
        self.assertEqual(github.csv_members(blob), ["role\nx\n"])

    def test_an_oversized_member_is_left_out(self):
        big = "role\n" + "x" * (github.MAX_CSV_BYTES + 1)
        blob = archive({"big.csv": big, "small.csv": "role\nx\n"})
        self.assertEqual(github.csv_members(blob), ["role\nx\n"])

    def test_a_traversing_member_name_is_only_read_in_memory(self):
        blob = archive({"../../etc/evil.csv": "role\nx\n"})
        self.assertEqual(github.csv_members(blob), ["role\nx\n"])


class TestRoleRuntimeCsvs(unittest.TestCase):
    def test_only_unexpired_role_runtimes_artifacts_are_downloaded(self):
        artifacts = [
            {
                "id": 1,
                "name": "role-runtimes-web-app-a",
                "expired": False,
                "size_in_bytes": 10,
            },
            {
                "id": 2,
                "name": "role-runtimes-web-app-b",
                "expired": True,
                "size_in_bytes": 10,
            },
            {
                "id": 3,
                "name": "inventory-web-app-a",
                "expired": False,
                "size_in_bytes": 10,
            },
            {
                "id": 4,
                "name": "role-runtimes-web-app-c",
                "expired": False,
                "size_in_bytes": github.MAX_ARTIFACT_BYTES + 1,
            },
        ]
        downloads = []

        def gh(args):
            if args[1] == "--paginate":
                return lines(*artifacts)
            downloads.append(args[1])
            return archive({"r.csv": "role\nweb-app-a\n"})

        self.assertEqual(github.role_runtime_csvs(gh, REPO, 77), ["role\nweb-app-a\n"])
        self.assertEqual(downloads, [f"repos/{REPO}/actions/artifacts/1/zip"])


if __name__ == "__main__":
    unittest.main()
