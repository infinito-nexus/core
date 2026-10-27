import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

HANDLERS = PROJECT_ROOT / "roles" / "sys-svc-compose" / "handlers" / "compose.yml"
TEMPLATE_SUFFIX = "/" + ROLE_FILE_TEMPL_COMPOSE


class TestComposeFileRerenderedAtFlush(unittest.TestCase):
    def setUp(self):
        self.handlers = load_yaml_any(str(HANDLERS))

    def index_of(self, predicate):
        matches = [
            index for index, handler in enumerate(self.handlers) if predicate(handler)
        ]
        self.assertEqual(len(matches), 1, matches)
        return matches[0]

    def rerender(self):
        return self.handlers[
            self.index_of(
                lambda h: str(h.get("stack_host_template", {}).get("src", "")).endswith(
                    TEMPLATE_SUFFIX
                )
            )
        ]

    def test_compose_file_is_rendered_again_before_compose_pull_and_up(self):
        rerender = self.index_of(
            lambda h: str(h.get("stack_host_template", {}).get("src", "")).endswith(
                TEMPLATE_SUFFIX
            )
        )
        pull = self.index_of(
            lambda h: (
                "pull.py" in str(h.get("ansible.builtin.script", {}).get("cmd", ""))
            )
        )
        up = self.index_of(
            lambda h: "compose up" in str(h.get("ansible.builtin.shell", ""))
        )
        self.assertLess(rerender, pull)
        self.assertLess(rerender, up)

    def test_rerender_listens_where_compose_up_listens(self):
        up = self.handlers[
            self.index_of(
                lambda h: "compose up" in str(h.get("ansible.builtin.shell", ""))
            )
        ]
        self.assertEqual(sorted(self.rerender()["listen"]), sorted(up["listen"]))

    def test_rerender_writes_the_file_the_tasks_write(self):
        args = self.rerender()["stack_host_template"]
        self.assertEqual(
            args["dest"], "{{ lookup('container', application_id, 'files.compose') }}"
        )
        self.assertEqual(args["mode"], "0640")
        self.assertIs(args["force"], True)

    def test_rerender_name_is_static_so_ansible_keeps_one_instance(self):
        self.assertNotIn("{{", self.rerender()["name"])

    def test_role_without_compose_template_skips_the_rerender(self):
        self.assertIn("is file", self.rerender()["when"])


if __name__ == "__main__":
    unittest.main()
