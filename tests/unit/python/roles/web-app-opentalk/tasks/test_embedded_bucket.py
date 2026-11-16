from __future__ import annotations

import unittest
from pathlib import Path

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "web-app-opentalk" / "tasks"
WAIT = "⏳ Wait until the sidecar created the embedded OpenTalk bucket"


def task_files() -> list[Path]:
    return sorted(
        Path(path)
        for path in iter_project_files(extensions=(".yml",))
        if Path(path).is_relative_to(TASKS)
    )


def flatten(items):
    for item in items or []:
        yield item
        yield from flatten(item.get("block"))


def tasks() -> list[dict]:
    return [task for path in task_files() for task in flatten(load_yaml_any(path))]


class TestEmbeddedBucket(unittest.TestCase):
    def test_role_never_creates_the_bucket_the_sidecar_creates(self) -> None:
        files = task_files()
        self.assertTrue(files)
        for path in files:
            with self.subTest(path=path.name):
                self.assertNotIn("s3.bucket.create", repr(load_yaml_any(path)))

    def test_deploy_waits_until_the_sidecar_bucket_is_listed(self) -> None:
        wait = next(task for task in tasks() if task.get("name") == WAIT)
        self.assertIn("s3.bucket.list", wait["ansible.builtin.shell"])
        self.assertIn("seaweedfs_bucket_names", wait["until"])
        self.assertGreater(wait["retries"], 0)


if __name__ == "__main__":
    unittest.main()
