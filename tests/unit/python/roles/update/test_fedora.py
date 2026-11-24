import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles/update/tasks/fedora.yml"
MAKECACHE = ["dnf", "makecache", "--refresh", "-y"]
MIRROR_PUSH_SECONDS = 300


def makecache_task():
    return next(
        task
        for task in load_yaml_any(str(TASKS))
        if task.get("ansible.builtin.command", {}).get("argv") == MAKECACHE
    )


class FedoraMetadataRefreshTests(unittest.TestCase):
    def test_the_metadata_refresh_retries_until_dnf_succeeds(self):
        task = makecache_task()

        self.assertEqual(task["until"], f"{task['register']}.rc == 0")

    def test_the_retries_outlast_a_mirror_push(self):
        task = makecache_task()

        self.assertGreaterEqual(task["retries"] * task["delay"], MIRROR_PUSH_SECONDS)


if __name__ == "__main__":
    unittest.main()
