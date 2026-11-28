import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

TASKS = PROJECT_ROOT / "roles" / "test-e2e-playwright" / "tasks"
STAGE_DIR = "{{ _playwright_stage_dir }}"
ENV_FILE = "{{ _playwright_stage_dir }}/.env"


def mode_of(tasks, module, key, path):
    """Args:
        tasks: the parsed task list.
        module: the module whose task writes the path.
        key: the module argument that holds the path.
        path: the templated path.

    Returns:
        The mode of every task of that module writing that path.
    """
    return [
        task[module].get("mode")
        for task in tasks
        if isinstance(task.get(module), dict)
        and task[module].get(key) == path
        and task[module].get("state") != "absent"
    ]


class TestStageModes(unittest.TestCase):
    def setUp(self):
        self.run_one = load_yaml_str(read_text(str(TASKS / "02_run_one.yml")))
        self.run_pass = load_yaml_str(read_text(str(TASKS / "03_run_pass.yml")))

    def test_only_the_deploying_user_enters_the_stage_dir(self):
        self.assertEqual(
            mode_of(self.run_one, "ansible.builtin.file", "path", STAGE_DIR), ["0700"]
        )

    def test_only_the_deploying_user_reads_the_rendered_env(self):
        self.assertEqual(
            mode_of(self.run_pass, "ansible.builtin.copy", "dest", ENV_FILE), ["0600"]
        )

    def test_negative_control_a_world_readable_env_fails(self):
        planted = [
            {
                **task,
                "ansible.builtin.copy": {
                    **task["ansible.builtin.copy"],
                    "mode": "0644",
                },
            }
            if isinstance(task.get("ansible.builtin.copy"), dict)
            and task["ansible.builtin.copy"].get("dest") == ENV_FILE
            else task
            for task in self.run_pass
        ]
        self.assertNotEqual(
            mode_of(planted, "ansible.builtin.copy", "dest", ENV_FILE), ["0600"]
        )


if __name__ == "__main__":
    unittest.main()
