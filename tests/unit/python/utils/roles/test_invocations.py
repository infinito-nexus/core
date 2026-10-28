import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml
from utils.roles.invocations import (
    deploy_closure,
    expand_roles,
    role_invocations,
    stage_files,
    stage_invocations,
)
from utils.roles.mapping import (
    ROLE_FILE_HANDLERS_MAIN,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

ROLES = ("role-a", "role-b", "role-c", "sys-ctl-hlth-x", "sys-ctl-hlth-y")


def _role_file(role: str, role_file: str) -> str:
    return f"roles/{role}/{role_file}"


class _TreeMixin:
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        for role in ROLES:
            (self.root / "roles" / role / "tasks").mkdir(parents=True)

    def _write(self, relative: str, payload) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        dump_yaml(str(path), payload)
        return path

    def _invoked(self, tasks, role: str = "role-a") -> frozenset[str]:
        self._write(_role_file(role, ROLE_FILE_TASKS_MAIN), tasks)
        return role_invocations(str(self.root / "roles"), role)


class TestRoleInvocations(_TreeMixin, unittest.TestCase):
    def test_a_literal_include_role_is_an_edge(self):
        self.assertEqual(
            self._invoked([{"include_role": {"name": "role-b"}}]), {"role-b"}
        )

    def test_an_import_role_is_an_edge(self):
        self.assertEqual(
            self._invoked([{"ansible.builtin.import_role": {"name": "role-b"}}]),
            {"role-b"},
        )

    def test_a_literal_loop_names_every_item(self):
        tasks = [
            {
                "include_role": {"name": "{{ dep }}"},
                "loop": ["role-b", "role-c"],
                "loop_control": {"loop_var": "dep"},
            }
        ]
        self.assertEqual(self._invoked(tasks), {"role-b", "role-c"})

    def test_a_template_with_a_literal_part_matches_a_glob(self):
        tasks = [{"include_role": {"name": "sys-ctl-hlth-{{ kind }}"}}]
        self.assertEqual(self._invoked(tasks), {"sys-ctl-hlth-x", "sys-ctl-hlth-y"})

    def test_a_role_name_handed_over_as_a_var_is_an_edge(self):
        tasks = [
            {
                "include_tasks": "utils/load/app.yml",
                "vars": {"load_app_id": "role-b"},
            }
        ]
        self.assertEqual(self._invoked(tasks), {"role-b"})

    def test_including_a_task_file_of_another_role_is_an_edge(self):
        tasks = [
            {
                "include_tasks": "{{ lookup('path_absolute', 'roles/role-c/tasks/x.yml') }}"
            }
        ]
        self.assertEqual(self._invoked(tasks), {"role-c"})

    def test_includes_nested_in_blocks_count(self):
        tasks = [
            {
                "block": [{"include_role": {"name": "role-b"}}],
                "rescue": [{"include_role": {"name": "role-c"}}],
            }
        ]
        self.assertEqual(self._invoked(tasks), {"role-b", "role-c"})

    def test_conditions_do_not_hide_an_edge(self):
        tasks = [{"include_role": {"name": "role-b"}, "when": "false"}]
        self.assertEqual(self._invoked(tasks), {"role-b"})

    def test_a_bare_template_falls_back_to_quoted_role_names_in_vars(self):
        self._write(
            _role_file("role-a", ROLE_FILE_VARS_MAIN),
            {"DEPS": "{{ ['role-b'] + (['role-c'] if flag else []) }}"},
        )
        tasks = [
            {
                "include_role": {"name": "{{ dep }}"},
                "loop": "{{ DEPS }}",
                "loop_control": {"loop_var": "dep"},
            }
        ]
        self.assertEqual(self._invoked(tasks), {"role-b", "role-c"})

    def test_quoted_names_are_ignored_while_every_include_resolves(self):
        self._write(_role_file("role-a", ROLE_FILE_VARS_MAIN), {"OTHER": "{{ 'role-c' }}"})
        self.assertEqual(
            self._invoked([{"include_role": {"name": "role-b"}}]), {"role-b"}
        )

    def test_unknown_role_names_are_dropped(self):
        self.assertEqual(
            self._invoked([{"include_role": {"name": "role-missing"}}]), frozenset()
        )

    def test_a_role_does_not_invoke_itself(self):
        self.assertEqual(
            self._invoked([{"include_role": {"name": "role-a"}}]), frozenset()
        )

    def test_handlers_count(self):
        self._write(
            _role_file("role-a", ROLE_FILE_HANDLERS_MAIN),
            [{"include_role": {"name": "role-c"}}],
        )
        self.assertEqual(
            self._invoked([{"include_role": {"name": "role-b"}}]), {"role-b", "role-c"}
        )


class TestStageInvocations(_TreeMixin, unittest.TestCase):
    def _stage(self, tasks):
        return self._write("tasks/stages/01_constructor.yml", tasks)

    def test_a_group_membership_gate_closes_for_a_non_member(self):
        path = self._stage(
            [{"include_role": {"name": "role-b"}, "when": "'role-b' in group_names"}]
        )
        self.assertEqual(
            stage_invocations(path, frozenset(ROLES), seeds=[], group_names=[]), set()
        )

    def test_a_group_membership_gate_opens_for_a_member(self):
        path = self._stage(
            [{"include_role": {"name": "role-b"}, "when": "'role-b' in group_names"}]
        )
        self.assertEqual(
            stage_invocations(
                path, frozenset(ROLES), seeds=[], group_names=["role-b"]
            ),
            {"role-b"},
        )

    def test_an_application_allowed_gate_decides_on_the_seeds(self):
        path = self._stage(
            [
                {
                    "when": "'role-b' | application_allowed(group_names, whitelist)",
                    "block": [{"include_role": {"name": "role-b"}}],
                }
            ]
        )
        self.assertEqual(
            stage_invocations(
                path, frozenset(ROLES), seeds=[], group_names=["role-b"]
            ),
            set(),
        )
        self.assertEqual(
            stage_invocations(
                path, frozenset(ROLES), seeds=["role-b"], group_names=[]
            ),
            {"role-b"},
        )

    def test_any_other_condition_keeps_the_include(self):
        path = self._stage(
            [{"include_role": {"name": "role-c"}, "when": ["MODE_CLEANUP | bool"]}]
        )
        self.assertEqual(
            stage_invocations(path, frozenset(ROLES), seeds=[], group_names=[]),
            {"role-c"},
        )

    def test_stage_files_follow_the_host_types(self):
        for name in ("01_constructor", "02_server", "02_workstation", "03_destructor"):
            self._write(f"tasks/stages/{name}.yml", [])
        self.assertEqual(
            [path.name for path in stage_files(self.root, ["server"])],
            ["01_constructor.yml", "02_server.yml", "03_destructor.yml"],
        )


class TestClosure(_TreeMixin, unittest.TestCase):
    def test_invocations_are_followed_transitively(self):
        self._write(
            _role_file("role-b", ROLE_FILE_TASKS_MAIN),
            [{"include_role": {"name": "role-c"}}],
        )
        self._write(
            _role_file("role-a", ROLE_FILE_TASKS_MAIN),
            [{"include_role": {"name": "role-b"}}],
        )
        self.assertEqual(
            expand_roles({}, ["role-a"], project_root=self.root),
            {"role-a", "role-b", "role-c"},
        )

    def test_meta_dependencies_are_followed(self):
        self._write(
            _role_file("role-a", ROLE_FILE_META_MAIN), {"dependencies": ["role-c"]}
        )
        self.assertEqual(
            expand_roles({}, ["role-a"], project_root=self.root), {"role-a", "role-c"}
        )

    def test_the_deploy_closure_adds_the_stage_roles(self):
        self._write(
            "tasks/stages/01_constructor.yml", [{"include_role": {"name": "role-c"}}]
        )
        self.assertEqual(
            deploy_closure(
                {},
                ["role-a"],
                project_root=self.root,
                host_types=[],
                group_names=["role-a"],
            ),
            {"role-a", "role-c"},
        )


if __name__ == "__main__":
    unittest.main()
