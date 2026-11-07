# nocheck: workflow-references  fixture workflow names, not real files
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.meta.ci.iterate.names import (
    MODULE,
    NAME,
    module_name,
    path_words,
    plugin_names,
    start_symbols,
)
from cli.meta.ci.iterate.symbols import Index
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

FILTER = """
from utils.mid import VALUE


class FilterModule:
    def filters(self):
        return {"shout": str.upper, "whisper": str.lower}
"""
DYNAMIC = """
class FilterModule:
    def filters(self):
        return dict(make())
"""
TREE = {
    "utils/base.py": "VALUE = 1\n",
    "utils/mid.py": "from utils.base import VALUE\n",
    "utils/rel.py": "from .base import VALUE\n",
    "library/mod.py": "from ansible.module_utils.base import VALUE\n",
    "plugins/filter/shout.py": FILTER,
    "plugins/filter/loud.py": FILTER.replace('"shout"', '"loud"')
    .replace('"whisper"', '"quiet"')
    .replace("from utils.mid import VALUE\n", ""),
    "plugins/filter/dynamic.py": DYNAMIC,
    "plugins/lookup/greet.py": "class LookupModule:\n    pass\n",
    "plugins/lookup/helper.py": "def help():\n    return 1\n",
    f"roles/web-app-a/{ROLE_FILE_TASKS_MAIN}": "- debug:\n    msg: \"{{ 'x' | shout }}\"\n",
    "roles/web-app-b/templates/x.j2": "{{ lookup('greet') }}\n",
    "group_vars/all/10.yml": "GREETING: \"{{ lookup('greet') }}\"\nOTHER: 1\n",
    "group_vars/all/20.yml": "BROKEN: [\n",
    f"roles/web-app-c/{ROLE_FILE_VARS_MAIN}": 'c: "{{ GREETING }}"\n',
    "tests/unit/python/utils/test_base.py": "from utils.base import VALUE\n",
    "tasks/stages/x.yml": "- debug:\n    msg: \"{{ 'y' | loud }}\"\n",
    "cli/meta/tool.py": "import utils.base\n",
    f"roles/web-app-d/{ROLE_FILE_TASKS_MAIN}": "- debug:\n    msg: '{{ BROKEN_READER }}'\n",
    "cli/pkg/__main__.py": "x = 1\n",
    "roles/web-app-e/files/run.sh": "python3 -m cli.pkg\n",
    "scripts/lint/run.sh": "x\n",
    "scripts/lint/caller.sh": 'bash "$DIR/run.sh"\n',
    "scripts/lint/lonely.sh": "x\n",
    "Makefile": (
        "check:\n\tbash scripts/lint/caller.sh\n"
        ".PHONY: iterate-plan\n# Usage: make iterate-plan\n"
        "iterate-plan:\n\tpython3 -m cli.plan\n"
        "compose-deploy:\n\tpython3 -m cli.deploys\n"
        "lint-markdown:\n\tbash scripts/ci/dispatch.sh markdown\n"
        "lint-python:\n\tbash scripts/ci/dispatch.sh python\n"
    ),
    "cli/plan/__main__.py": "x = 1\n",
    "cli/deploys/__main__.py": "x = 1\n",
    "scripts/ci/dispatch.sh": 'bash "scripts/ci/${kind}.sh"\n',
    "scripts/ci/markdown.sh": "x\n",
    "scripts/github/zip/compose_up.sh": "x\n",
    ".github/workflows/up.yml": 'run: bash "scripts/github/zip/${kind}_up.sh"\n',
    "tests/unit/python/cli/test_roles.py": 'ROLE = "web-app-a"\n',
    "tests/unit/python/cli/test_longer_role.py": 'ROLE = "web-app-ab"\n',
    "scripts/github/step.sh": "x\n",
    "scripts/github/split.sh": "x\n",
    "tests/unit/python/cli/test_split.py": 'P = ROOT / "scripts" / "github" / "split.sh"\n',
    "tests/unit/python/cli/test_other.py": 'N = "split.sh"\n',
    "tests/utils/helper.py": "X = 1\n",
    "tests/utils/middle.py": "from tests.utils.helper import X\n",
    "tests/unit/python/test_uses_helper.py": "from tests.utils.middle import X\n",
    ".github/workflows/x.yml": "run: bash scripts/github/step.sh\n",
}


class _Tree(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for rel, text in TREE.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.index = Index(self.root, sorted(TREE))

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestModuleName(unittest.TestCase):
    def test_dotted(self) -> None:
        self.assertEqual(module_name("utils/cache/files.py"), "utils.cache.files")

    def test_package_init(self) -> None:
        self.assertEqual(module_name("utils/cache/__init__.py"), "utils.cache")

    def test_role_file_has_no_import_name(self) -> None:
        self.assertEqual(module_name("roles/web-app-a/files/x.py"), "")

    def test_package_main_answers_to_the_package(self) -> None:
        self.assertEqual(
            module_name("cli/meta/ci/validate/__main__.py"), "cli.meta.ci.validate"
        )


class TestStartSymbols(unittest.TestCase):
    def test_main_searches_the_package_and_its_main(self) -> None:
        self.assertEqual(
            start_symbols("cli/pkg/__main__.py"),
            {(MODULE, "cli.pkg"), (MODULE, "cli.pkg.__main__")},
        )

    def test_non_python_file_is_named_by_its_path(self) -> None:
        self.assertEqual(
            start_symbols("scripts/lint/run.sh"), {("path", "scripts/lint/run.sh")}
        )

    def test_path_words_keep_a_directory(self) -> None:
        self.assertEqual(
            path_words("scripts/lint/run.sh"), {"scripts/lint/run.sh", "lint/run.sh"}
        )


class TestPluginNames(unittest.TestCase):
    def test_filter_names_are_the_literal_keys(self) -> None:
        self.assertEqual(plugin_names("f.py", "filter", FILTER), ("shout", "whisper"))

    def test_dynamic_filter_names_are_unreadable(self) -> None:
        self.assertIsNone(plugin_names("f.py", "filter", DYNAMIC))

    def test_lookup_is_its_stem(self) -> None:
        self.assertEqual(
            plugin_names(
                "plugins/lookup/greet.py", "lookup", TREE["plugins/lookup/greet.py"]
            ),
            ("greet",),
        )

    def test_lookup_helper_registers_nothing(self) -> None:
        self.assertEqual(
            plugin_names("plugins/lookup/helper.py", "lookup", "x = 1\n"), ()
        )

    def test_module_is_its_stem(self) -> None:
        self.assertEqual(
            plugin_names("library/copy_batch.py", "module", ""), ("copy_batch",)
        )

    def test_unparsable_filter_is_unreadable(self) -> None:
        self.assertIsNone(plugin_names("f.py", "filter", "class FilterModule(:\n"))


class TestImporters(_Tree):
    def test_absolute_relative_and_module_utils_imports(self) -> None:
        self.assertEqual(
            self.index.importers("utils.base"),
            {
                "utils/mid.py",
                "utils/rel.py",
                "library/mod.py",
                "tests/unit/python/utils/test_base.py",
                "cli/meta/tool.py",
            },
        )


class TestReach(_Tree):
    def test_module_reaches_role_through_a_filter_and_its_test(self) -> None:
        reach = self.index.reach({(MODULE, "utils.base")})
        self.assertEqual((set(reach.roles), reach.full), ({"web-app-a"}, ""))
        self.assertIn("tests/unit/python/utils/test_base.py", reach.tests)

    def test_lookup_reaches_template_and_group_vars_reader(self) -> None:
        reach = self.index.reach({(NAME, "greet")})
        self.assertEqual(set(reach.roles), {"web-app-b", "web-app-c"})

    def test_global_consumer_widens_to_the_full_set(self) -> None:
        reach = self.index.reach({(NAME, "loud")})
        self.assertIn("tasks/stages/x.yml", reach.full)

    def test_unparsable_group_vars_consumer_widens(self) -> None:
        self.assertIn("does not parse", self.index.reach({(NAME, "BROKEN")}).full)

    def test_unconsumed_name_reaches_nothing(self) -> None:
        reach = self.index.reach({(NAME, "nobody_calls_this")})
        self.assertEqual((reach.roles, reach.tests, reach.full), ({}, set(), ""))

    def test_word_match_does_not_hit_a_longer_name(self) -> None:
        reach = self.index.reach({(NAME, "GREET")})
        self.assertEqual(reach.roles, {})

    def test_python_m_caller_reaches_the_role_of_a_package_main(self) -> None:
        reach = self.index.reach(start_symbols("cli/pkg/__main__.py"))
        self.assertEqual(set(reach.roles), {"web-app-e"})

    def test_sibling_caller_named_by_the_makefile_widens(self) -> None:
        reach = self.index.reach(start_symbols("scripts/lint/run.sh"))
        self.assertIn("Makefile", reach.full)

    def test_workflow_consumer_widens(self) -> None:
        reach = self.index.reach(start_symbols("scripts/github/step.sh"))
        self.assertIn(".github/workflows/x.yml", reach.full)

    def test_test_that_quotes_the_path_segments_consumes_the_script(self) -> None:
        reach = self.index.reach(start_symbols("scripts/github/split.sh"))
        self.assertEqual(
            (reach.tests, reach.full), ({"tests/unit/python/cli/test_split.py"}, "")
        )

    def test_test_helper_reaches_the_tests_importing_it_transitively(self) -> None:
        reach = self.index.reach(start_symbols("tests/utils/helper.py"))
        self.assertEqual(reach.tests, {"tests/unit/python/test_uses_helper.py"})

    def test_negative_control_unnamed_script_reaches_nothing(self) -> None:
        reach = self.index.reach(start_symbols("scripts/lint/lonely.sh"))
        self.assertEqual((reach.roles, reach.full), ({}, ""))


class TestMakefileAndDispatchers(_Tree):
    def test_module_of_a_tooling_target_is_that_target(self) -> None:
        reach = self.index.reach(start_symbols("cli/plan/__main__.py"))
        self.assertEqual((reach.full, reach.targets), ("", {"iterate-plan"}))

    def test_negative_control_module_of_a_deploy_target_widens(self) -> None:
        reach = self.index.reach(start_symbols("cli/deploys/__main__.py"))
        self.assertIn("make compose-deploy", reach.full)

    def test_dispatched_script_reaches_only_the_target_passing_it(self) -> None:
        reach = self.index.reach(start_symbols("scripts/ci/markdown.sh"))
        self.assertEqual(
            (reach.full, reach.targets, reach.tooling),
            ("", {"lint-markdown"}, {"scripts/ci/dispatch.sh"}),
        )

    def test_dispatcher_reaches_every_target_naming_it(self) -> None:
        reach = self.index.reach(start_symbols("scripts/ci/dispatch.sh"))
        self.assertEqual(reach.targets, {"lint-markdown", "lint-python"})

    def test_workflow_interpolating_the_script_widens(self) -> None:
        reach = self.index.reach(start_symbols("scripts/github/zip/compose_up.sh"))
        self.assertIn(".github/workflows/up.yml", reach.full)

    def test_tests_naming_a_role_skip_a_longer_name(self) -> None:
        self.assertEqual(
            self.index.tests_naming("web-app-a"),
            {"tests/unit/python/cli/test_roles.py"},
        )


if __name__ == "__main__":
    unittest.main()
