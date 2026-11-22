import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

FLAG = "utils/once/flag.yml"
LOADER = "list_or_shoot.yml"


def order_findings(tasks):
    """Args:
        tasks: the top-level tasks of a role's tasks/00_core.yml.

    Returns:
        A message when the role shoots post-load roles through the service
        loader before it sets its run-once flag.
    """
    flag = loader = None
    for index, task in enumerate(tasks or []):
        if not isinstance(task, dict):
            continue
        if task.get("include_tasks") == FLAG and flag is None:
            flag = index
        include = task.get("ansible.builtin.include_role") or task.get("include_role")
        if isinstance(include, dict) and include.get("tasks_from") == LOADER:
            loader = index if loader is None else loader
    if flag is not None and loader is not None and loader < flag:
        return [
            f"post-load roles shot at task {loader}, run-once flag set at task {flag}"
        ]
    return []


def offenders(roles):
    """Args:
        roles: the roles directory.

    Returns:
        ``role: message`` for every role whose core tasks shoot post-load roles
        before the run-once flag.
    """
    found = []
    for core in sorted(roles.glob("*/tasks/00_core.yml")):
        text = read_text(str(core))
        if FLAG not in text or LOADER not in text:
            continue
        found.extend(
            f"{core.parent.parent.name}: {message}"
            for message in order_findings(load_yaml_str(text))
        )
    return found


class TestOnceFlagBeforePostLoad(unittest.TestCase):
    def test_every_role_sets_its_flag_before_it_shoots_post_load_roles(self):
        self.assertEqual(offenders(PROJECT_ROOT / "roles"), [])

    def test_negative_control_the_old_container_order_recurses(self):
        core = PROJECT_ROOT / "roles" / "sys-svc-container" / "tasks" / "00_core.yml"
        tasks = load_yaml_str(read_text(str(core)))
        flag = next(i for i, t in enumerate(tasks) if t.get("include_tasks") == FLAG)
        planted = [t for t in tasks if t.get("include_tasks") != FLAG] + [tasks[flag]]
        self.assertEqual(order_findings(tasks), [])
        self.assertNotEqual(order_findings(planted), [])


if __name__ == "__main__":
    unittest.main()
