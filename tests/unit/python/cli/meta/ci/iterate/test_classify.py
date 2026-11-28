# nocheck: workflow-references  fixture workflow names, not real files
from __future__ import annotations

import unittest

from cli.meta.ci.iterate import classify as subject
from cli.meta.ci.iterate.classify import changed_keys, classify
from cli.meta.ci.iterate.names import MODULE, NAME
from cli.meta.ci.iterate.symbols import Reach
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

OLD = "a: 1\n"
NEW = "a: 2\n"
TASKS = f"roles/web-app-a/{ROLE_FILE_TASKS_MAIN}"


class _Index:
    """Records what the classifier asks the symbol index and answers *reach*."""

    def __init__(self, reach: Reach | None = None, naming: set | None = None) -> None:
        self.answer = reach or Reach()
        self.naming = naming or set()
        self.asked: list[set] = []

    def reach(self, start):
        self.asked.append(set(start))
        return self.answer

    def tests_naming(self, role):
        return self.naming


def _reader(old: str | None, new: str | None):
    return lambda path: (old, new)


def _absent(path: str) -> bool:
    return False


def _run(path, old, new, index=None, exists=None):
    return classify(path, _reader(old, new), index or _Index(), exists or _absent)


class TestRolePaths(unittest.TestCase):
    def test_role_file_seeds_its_role(self) -> None:
        change = _run(TASKS, OLD, NEW)
        self.assertEqual((change.effect, change.roles), (subject.SEED, ("web-app-a",)))

    def test_role_file_runs_the_tests_naming_its_role(self) -> None:
        naming = {"tests/unit/python/cli/test_reads_roles.py"}
        change = _run(TASKS, OLD, NEW, _Index(naming=naming))
        self.assertEqual(change.tests, tuple(naming))

    def test_deploy_read_marker_drop_seeds_its_role(self) -> None:
        old = "a:\n  options: # nocheck: inventory-open-subtree why\n    k: 1\n"
        change = _run(TASKS, old, "a:\n  options:\n    k: 1\n")
        self.assertEqual(
            (change.effect, change.roles, change.format_only),
            (subject.SEED, ("web-app-a",), False),
        )

    def test_format_only_role_file_reaches_nothing(self) -> None:
        change = _run(TASKS, "a: 1\n", "a:   1 # c\n")
        self.assertEqual((change.effect, change.format_only), (subject.NONE, True))

    def test_lint_directive_edit_runs_the_lint_suite(self) -> None:
        change = _run(TASKS, "a: 1\n", "a: 1 # nocheck: role-file-spot\n")
        self.assertEqual(
            (change.effect, change.tests, change.roles),
            (subject.TESTS, (subject.LINT_SUITE,), ()),
        )

    def test_type_swap_seeds_its_role(self) -> None:
        for old, new in (
            ("a: 1\n", "a: true\n"),
            ("a: 0\n", "a: false\n"),
            ("a: 1\n", "a: 1.0\n"),
        ):
            with self.subTest(old=old, new=new):
                change = _run(TASKS, old, new)
                self.assertEqual(
                    (change.effect, change.roles), (subject.SEED, ("web-app-a",))
                )

    def test_role_document_seeds_only_its_role(self) -> None:
        change = _run("roles/web-app-a/README.md", None, None)
        self.assertEqual(
            (change.effect, change.roles), (subject.DOC_SEED, ("web-app-a",))
        )

    def test_role_template_is_never_format_only(self) -> None:
        change = _run("roles/web-app-a/templates/x.j2", "x\n", "x\n")
        self.assertEqual(change.effect, subject.SEED)


class TestNonRolePaths(unittest.TestCase):
    def test_test_file_runs_itself(self) -> None:
        change = _run("tests/unit/python/x/test_a.py", None, None)
        self.assertEqual(
            (change.effect, change.tests),
            (subject.TESTS, ("tests/unit/python/x/test_a.py",)),
        )

    def test_test_helper_runs_the_tests_importing_it(self) -> None:
        index = _Index(Reach(tests={"tests/unit/python/x/test_a.py"}))
        change = _run("tests/utils/x.py", OLD, NEW, index)
        self.assertEqual(
            (change.effect, change.tests),
            (subject.TESTS, ("tests/unit/python/x/test_a.py",)),
        )

    def test_negative_control_unimported_helper_runs_its_directory(self) -> None:
        change = _run("tests/utils/x.py", OLD, NEW)
        self.assertEqual(
            (change.effect, change.tests), (subject.TESTS, ("tests/utils",))
        )

    def test_test_fixture_runs_its_directory(self) -> None:
        change = _run("tests/unit/python/x/fixture.yml", OLD, NEW)
        self.assertEqual(change.tests, ("tests/unit/python/x",))

    def test_document_reaches_nothing(self) -> None:
        self.assertEqual(_run("docs/a.md", None, None).effect, subject.NONE)

    def test_unknown_path_widens(self) -> None:
        self.assertEqual(_run("Makefile", None, None).effect, subject.FULL)

    def test_workflow_widens(self) -> None:
        self.assertEqual(_run(".github/workflows/x.yml", OLD, NEW).effect, subject.FULL)

    def test_tooling_script_reaches_nothing(self) -> None:
        self.assertEqual(_run("scripts/lint/x.sh", None, None).effect, subject.NONE)

    def test_format_only_shared_plugin_reaches_nothing(self) -> None:
        index = _Index()
        change = _run("plugins/lookup/x.py", "x = 'a'\n", 'x = "a"\n', index)
        self.assertEqual((change.effect, index.asked), (subject.NONE, []))


class TestSymbols(unittest.TestCase):
    def test_group_vars_asks_for_the_changed_keys_only(self) -> None:
        index = _Index(Reach(roles={"web-app-b": "roles/web-app-b/x.yml names A"}))
        change = _run("group_vars/all/1.yml", "A: 1\nB: 2\n", "A: 3\nB: 2\n", index)
        self.assertEqual(index.asked, [{(NAME, "A")}])
        self.assertEqual((change.effect, change.roles), (subject.SEED, ("web-app-b",)))

    def test_unparsable_group_vars_widen(self) -> None:
        self.assertEqual(
            _run("group_vars/all/1.yml", "A: 1\n", "A: [\n").effect, subject.FULL
        )

    def test_plugin_asks_for_old_and_new_names_and_its_module(self) -> None:
        old = "class FilterModule:\n    def filters(self):\n        return {'a': 1}\n"
        new = "class FilterModule:\n    def filters(self):\n        return {'b': 1}\n"
        index = _Index()
        _run("plugins/filter/x.py", old, new, index)
        self.assertEqual(
            index.asked, [{(NAME, "a"), (NAME, "b"), (MODULE, "plugins.filter.x")}]
        )

    def test_reach_into_deploy_machinery_widens(self) -> None:
        index = _Index(Reach(full="cli/administration/x.py imports y"))
        self.assertEqual(
            _run("utils/y.py", "x = 1\n", "x = 2\n", index).effect, subject.FULL
        )

    def test_full_reach_keeps_its_tests_and_the_mirrored_test(self) -> None:
        found = "tests/unit/python/utils/test_reader.py"
        index = _Index(Reach(full="Makefile names y", tests={found}))
        change = _run(
            "utils/y.py",
            "x = 1\n",
            "x = 2\n",
            index,
            exists=lambda p: p.endswith("test_y.py"),
        )
        self.assertEqual(
            (change.effect, change.tests),
            (subject.FULL, (found, "tests/unit/python/utils/test_y.py")),
        )

    def test_tooling_target_runs_as_a_test(self) -> None:
        index = _Index(Reach(targets={"lint-markdown"}, tooling={"scripts/x.sh"}))
        change = _run("cli/meta/ci/q.py", "x = 1\n", "x = 2\n", index)
        self.assertEqual(
            (change.effect, change.targets), (subject.TESTS, ("lint-markdown",))
        )

    def test_unconsumed_module_runs_its_mirrored_test(self) -> None:
        change = _run(
            "cli/meta/ci/q.py",
            "x = 1\n",
            "x = 2\n",
            exists=lambda p: p.endswith("test_q.py"),
        )
        self.assertEqual(
            (change.effect, change.tests),
            (subject.TESTS, ("tests/unit/python/cli/meta/ci/test_q.py",)),
        )


class TestChangedKeys(unittest.TestCase):
    def test_added_removed_and_changed_keys(self) -> None:
        self.assertEqual(changed_keys("a: 1\nb: 2\n", "b: 3\nc: 1\n"), {"a", "b", "c"})

    def test_new_file_changes_every_key(self) -> None:
        self.assertEqual(changed_keys(None, "a: 1\n"), {"a"})

    def test_non_mapping_is_unreadable(self) -> None:
        self.assertIsNone(changed_keys("a: 1\n", "- 1\n"))


if __name__ == "__main__":
    unittest.main()
