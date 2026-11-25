import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles/update/tasks/arch.yml"
HELPER = "shell/alarm_mirror.sh"
DOWNLOAD_FAILED = "failed to retrieve some files"


def helper_verb(task):
    script = task.get("ansible.builtin.script") or {}
    words = (script.get("cmd", "") if isinstance(script, dict) else script).split()
    return words[1] if words[:1] == [HELPER] else None


def index_of(tasks, match):
    return next(index for index, task in enumerate(tasks) if match(task))


def upgrade_block(tasks):
    return next(
        task
        for task in tasks
        if any(
            (child.get("community.general.pacman") or {}).get("upgrade")
            for child in task.get("block", [])
        )
    )


class ArchMirrorTests(unittest.TestCase):
    def test_the_geo_host_is_demoted_before_the_databases_refresh(self):
        tasks = load_yaml_any(str(TASKS))
        demote = index_of(tasks, lambda task: helper_verb(task) == "demote")
        refresh = index_of(
            tasks,
            lambda task: (task.get("community.general.pacman") or {}).get(
                "update_cache"
            ),
        )

        self.assertLess(demote, refresh)

    def test_the_demote_decides_by_exit_code_never_by_output(self):
        tasks = load_yaml_any(str(TASKS))
        demote = tasks[index_of(tasks, lambda task: helper_verb(task) == "demote")]
        register = demote["register"]

        self.assertEqual(demote["changed_when"], f"{register}.rc == 3")
        self.assertEqual(demote["failed_when"], f"{register}.rc not in [0, 3]")

    def test_only_a_failed_download_reaches_the_mirror_retry(self):
        rescue = upgrade_block(load_yaml_any(str(TASKS)))["rescue"]

        self.assertIn("ansible.builtin.fail", rescue[0])
        self.assertIn(DOWNLOAD_FAILED, rescue[0]["when"])
        self.assertIn("not in", rescue[0]["when"])
        self.assertEqual(helper_verb(rescue[1]), "retry")

    def test_a_failure_no_mirror_retried_is_re_raised(self):
        rescue = upgrade_block(load_yaml_any(str(TASKS)))["rescue"]
        register = rescue[1]["register"]

        self.assertIs(rescue[1]["failed_when"], False)
        self.assertIn("ansible.builtin.fail", rescue[-1])
        self.assertEqual(
            rescue[-1]["when"], f"{register} is skipped or {register}.rc != 0"
        )


if __name__ == "__main__":
    unittest.main()
