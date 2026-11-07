import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

HANDLERS = PROJECT_ROOT / "roles" / "sys-svc-compose" / "handlers" / "compose.yml"
REHASH_TASKS = "roles/sys-svc-compose/tasks/utils/rehash_configs.yml"


class TestComposeHashesUpdatedAtFlush(unittest.TestCase):
    def setUp(self):
        self.handlers = load_yaml_any(str(HANDLERS))

    def index_of(self, predicate):
        matches = [
            index for index, handler in enumerate(self.handlers) if predicate(handler)
        ]
        self.assertEqual(len(matches), 1, matches)
        return matches[0]

    def rehash_index(self):
        return self.index_of(
            lambda h: REHASH_TASKS in str(h.get("ansible.builtin.include_tasks", ""))
        )

    def test_hashes_are_updated_before_compose_pull_and_up(self):
        pull = self.index_of(
            lambda h: (
                "pull.py" in str(h.get("ansible.builtin.script", {}).get("cmd", ""))
            )
        )
        up = self.index_of(
            lambda h: "compose up" in str(h.get("ansible.builtin.shell", ""))
        )
        self.assertLess(self.rehash_index(), pull)
        self.assertLess(self.rehash_index(), up)

    def test_rehash_listens_where_compose_up_listens(self):
        up = self.handlers[
            self.index_of(
                lambda h: "compose up" in str(h.get("ansible.builtin.shell", ""))
            )
        ]
        self.assertEqual(
            sorted(self.handlers[self.rehash_index()]["listen"]), sorted(up["listen"])
        )

    def test_no_handler_renders_a_role_template(self):
        for handler in self.handlers:
            self.assertNotIn("stack_host_template", handler, handler.get("name"))
            self.assertNotIn("ansible.builtin.template", handler, handler.get("name"))
            self.assertNotIn("template", handler, handler.get("name"))

    def test_rehash_tasks_render_no_template_and_read_no_role_variable(self):
        text = read_text(str(PROJECT_ROOT / REHASH_TASKS))
        self.assertNotIn("template", text)
        self.assertNotIn("abs_role_path_by_application_id", text)

    def test_rehash_name_is_static_so_ansible_keeps_one_instance(self):
        self.assertNotIn("{{", self.handlers[self.rehash_index()]["name"])


if __name__ == "__main__":
    unittest.main()
