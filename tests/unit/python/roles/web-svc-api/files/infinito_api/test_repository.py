from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.roles.mapping import ROLE_FILE_TASKS_MAIN
from utils.software import SOFTWARE_REPOSITORY

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-api" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

repository = importlib.import_module("infinito_api.repository")


def _snapshot(root: Path) -> Path:
    snapshot = root / "snapshot"
    tasks = snapshot / "roles" / "web-app-x" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "main.yml").write_text(
        "---\n# TODO: replace the placeholder\n", encoding="utf-8"
    )
    (snapshot / "roles" / "web-app-x" / "README.md").write_text(
        "# X\n", encoding="utf-8"
    )
    return snapshot


def _open(root: Path, forks: str = "off"):
    data = root / "data"
    data.mkdir(exist_ok=True)
    repo = repository.Repository(
        data / "repo.git", SOFTWARE_REPOSITORY, forks, _snapshot(root)
    )
    repo.initialize()
    return repo


class TestRepository(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _open(self.root)
        self.deployed = self.repo.resolve("deployed")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_snapshot_commits_to_the_same_sha_on_every_replica(self) -> None:
        with TemporaryDirectory() as other:
            self.assertEqual(_open(Path(other)).resolve("deployed"), self.deployed)

    def test_refs_resolve_by_sha_prefix_and_fork_owner(self) -> None:
        self.repo.git("update-ref", "refs/forks/alice/heads/feature", self.deployed)

        self.assertEqual(self.repo.resolve(self.deployed[:10]), self.deployed)
        self.assertEqual(self.repo.resolve("alice:feature"), self.deployed)
        with self.assertRaises(repository.NotFoundError):
            self.repo.resolve("bob:feature")
        with self.assertRaises(repository.NotFoundError):
            self.repo.resolve("main")

    def test_malformed_refs_never_reach_git(self) -> None:
        for ref in ("-x", "a..b", "x:y:z", "main@{1}", "bad owner:x", "/abs", "trail/"):
            with (
                self.subTest(ref=ref),
                self.assertRaises(repository.InvalidRequestError),
            ):
                self.repo.resolve(ref)

    def test_trees_and_files_are_read_from_the_commit(self) -> None:
        names = [
            entry["name"]
            for entry in self.repo.listing(self.deployed, "roles/web-app-x")
        ]
        self.assertEqual(sorted(names), ["README.md", "tasks"])
        self.assertEqual(
            [entry["name"] for entry in self.repo.listing(self.deployed, "")],
            ["roles"],
        )
        self.assertEqual(
            self.repo.blob(self.deployed, "roles/web-app-x/README.md"), b"# X\n"
        )
        self.assertEqual(
            self.repo.blobs(
                self.deployed, ["missing.txt", "roles/web-app-x/README.md"]
            ),
            {"roles/web-app-x/README.md": b"# X\n"},
        )
        with self.assertRaises(repository.NotFoundError):
            self.repo.blob(self.deployed, "roles/nothing.yml")
        with self.assertRaises(repository.NotFoundError):
            self.repo.listing(self.deployed, "roles/web-app-x/README.md")

    def test_paths_leaving_the_tree_are_rejected(self) -> None:
        for path in ("../etc/passwd", "/etc/passwd", "roles/../../x"):
            with (
                self.subTest(path=path),
                self.assertRaises(repository.InvalidRequestError),
            ):
                repository.Repository.check_path(path)
        self.assertEqual(repository.Repository.check_path("roles/"), "roles")

    def test_log_and_todos_describe_the_commit(self) -> None:
        (entry,) = self.repo.log(self.deployed, None, None, 5)
        self.assertEqual(
            (entry["sha"], entry["parents"], entry["message"]),
            (self.deployed, [], "deployed working tree"),
        )

        todos = self.repo.todos(self.deployed)
        self.assertEqual(todos["capped"], False)
        self.assertEqual(
            todos["items"],
            [
                {
                    "path": f"roles/web-app-x/{ROLE_FILE_TASKS_MAIN}",
                    "line": 2,
                    "kind": "TODO",
                    "text": "# TODO: replace the placeholder",
                }
            ],
        )

    def test_forks_come_from_the_setting_and_skip_malformed_names(self) -> None:
        listed = repository.Repository(
            self.root / "x.git",
            SOFTWARE_REPOSITORY,
            "alice/core bob/fork evil/../x",
            self.root,
        )

        self.assertEqual(self.repo.discover_forks(), {})
        self.assertEqual(
            listed.discover_forks(), {"alice": "alice/core", "bob": "bob/fork"}
        )

    def test_repositories_list_core_and_the_recorded_forks(self) -> None:
        self.repo.git("update-ref", "refs/tags/v1.0.0", self.deployed)
        self.repo.git("update-ref", "refs/forks/alice/heads/feature", self.deployed)
        self.repo.forks_file.write_text(
            json.dumps({"alice": "alice/core"}), encoding="utf-8"
        )

        root, fork = self.repo.repositories()

        self.assertEqual(
            (root["repository"], root["root"]), ("infinito-nexus/core", True)
        )
        self.assertEqual([tag["name"] for tag in root["tags"]], ["v1.0.0"])
        self.assertEqual(
            (fork["repository"], [b["name"] for b in fork["branches"]]),
            ("alice/core", ["feature"]),
        )
        self.assertFalse(self.repo.fetched())


if __name__ == "__main__":
    unittest.main()
