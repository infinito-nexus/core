# nocheck: workflow-references  fixture workflow names, not real files
from __future__ import annotations

import unittest

from cli.meta.ci.iterate import surface
from cli.meta.ci.iterate.surface import place
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN


class TestPlace(unittest.TestCase):
    def test_role_file_names_its_role_and_rest(self) -> None:
        self.assertEqual(
            place(f"roles/web-app-a/{ROLE_FILE_TASKS_MAIN}"),
            surface.Place(surface.ROLE, "web-app-a", ROLE_FILE_TASKS_MAIN, ""),
        )

    def test_resolve_scripts_are_deploy_machinery(self) -> None:
        for path in (
            "scripts/meta/resolve/image/ci.sh",
            "scripts/meta/resolve/apps.sh",
        ):
            with self.subTest(path=path):
                self.assertEqual(place(path).kind, surface.GLOBAL)

    def test_negative_control_lint_scripts_stay_tooling(self) -> None:
        self.assertEqual(place("scripts/lint/x.sh").kind, surface.TOOLING)

    def test_role_filter_plugin_is_a_plugin_of_its_role(self) -> None:
        where = place("roles/sys-svc-compose/filter_plugins/git_refspec.py")
        self.assertEqual(
            (where.kind, where.role, where.plugin),
            ("plugin", "sys-svc-compose", "filter"),
        )

    def test_nested_role_python_is_a_role_file(self) -> None:
        self.assertEqual(place("roles/r/filter_plugins/sub/x.py").kind, surface.ROLE)

    def test_shared_lookup_is_a_plugin(self) -> None:
        self.assertEqual(place("plugins/lookup/applications.py").plugin, "lookup")

    def test_library_module_is_a_module_plugin(self) -> None:
        self.assertEqual(place("library/copy_batch.py").plugin, "module")

    def test_plugin_package_init_is_a_module(self) -> None:
        self.assertEqual(place("plugins/__init__.py").kind, surface.MODULE)

    def test_document_outside_roles_is_docs(self) -> None:
        self.assertEqual(place("plugins/README.md").kind, surface.DOCS)

    def test_tests_win_over_suffix(self) -> None:
        self.assertEqual(place("tests/unit/python/a/README.md").kind, surface.TEST)

    def test_group_vars_yaml(self) -> None:
        self.assertEqual(place("group_vars/all/16_ai.yml").kind, surface.GROUP_VARS)

    def test_workflow(self) -> None:
        self.assertEqual(place(".github/workflows/x.yml").kind, surface.WORKFLOW)

    def test_deploy_machinery_is_global(self) -> None:
        self.assertEqual(place("cli/administration/deploy/x.py").kind, surface.GLOBAL)

    def test_playbook_is_global(self) -> None:
        self.assertEqual(place("playbook.yml").kind, surface.GLOBAL)

    def test_ci_tooling_is_tooling(self) -> None:
        self.assertEqual(place("cli/meta/ci/plan.py").kind, surface.TOOLING)

    def test_unlisted_script_dir_counts_as_deploy_machinery(self) -> None:
        self.assertEqual(place("scripts/brand-new/run.sh").kind, surface.GLOBAL)

    def test_listed_script_dir_is_tooling(self) -> None:
        self.assertEqual(place("scripts/lint/wrapper.sh").kind, surface.TOOLING)

    def test_utils_module(self) -> None:
        self.assertEqual(place("utils/cache/files.py").kind, surface.MODULE)

    def test_agents_yaml_is_unknown_not_tooling(self) -> None:
        self.assertEqual(place("agents/roles/robot/agent.yml").kind, surface.UNKNOWN)

    def test_makefile_is_unknown(self) -> None:
        self.assertEqual(place("Makefile").kind, surface.UNKNOWN)

    def test_bare_roles_entry_is_unknown(self) -> None:
        self.assertEqual(place("roles/README").kind, surface.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
