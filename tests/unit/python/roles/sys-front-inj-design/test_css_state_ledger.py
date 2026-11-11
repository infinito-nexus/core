from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

DESIGN_DIR = PROJECT_ROOT / "roles" / "sys-front-inj-design"
TASKS = DESIGN_DIR / ROLE_FILE_TASKS_MAIN
CORE = DESIGN_DIR / "tasks" / "00_core.yml"
VARS = DESIGN_DIR / ROLE_FILE_VARS_MAIN
STATE_FACTS = ("design_css_states",)

WORDPRESS = "web-app-wordpress"
MATRIX = "web-app-matrix"
CLEAR = "style.css"
ONION = "onion-style.css"


def _set_fact_with(tasks, fact):
    return next(
        task["set_fact"]
        for task in tasks
        if "set_fact" in task and fact in task["set_fact"]
    )


def _conditions(task):
    when = task["when"]
    return when if isinstance(when, list) else [when]


class Replay:
    """
    Args:
        tasks_path: the role's ``tasks/main.yml``.
        core_path: the role's run-once ``tasks/00_core.yml``.
        vars_path: the role's ``vars/main.yml``.
        stack_host: the value of ``IS_STACK_HOST``.
    """

    def __init__(self, tasks_path, core_path, vars_path, stack_host):
        tasks = load_yaml_any(str(tasks_path))
        core = load_yaml_any(str(core_path))
        self.deploy = next(task for task in tasks if "stack_host_copy" in task)
        self.remove = next(task for task in tasks if "ansible.builtin.file" in task)
        self.record = _set_fact_with(tasks, "design_js_one_liner")
        start = _set_fact_with(core, "design_assets_published")
        self.state = {fact: start[fact] for fact in STATE_FACTS}
        self.role_vars = DataLoader().load_from_file(
            str(vars_path), trusted_as_template=True
        )
        self.stack_host = stack_host
        self.files = {}
        self.operations = []

    def _templar(self, facts):
        return Templar(loader=DataLoader(), variables={**self.role_vars, **facts})

    def _holds(self, task, facts):
        templar = self._templar(facts)
        for condition in _conditions(task):
            result = templar.template(trust_as_template("{{ " + condition + " }}"))
            if not isinstance(result, bool):
                raise TypeError(f"{condition!r} rendered {result!r}")
            if not result:
                return False
        return True

    def vhost(self, application_id, sheet_file, css):
        """
        Args:
            application_id: the role the vhost belongs to.
            sheet_file: the ``app_style_file`` fact of the vhost's network.
            css: the ``app_style_css`` fact, empty when the role ships none.
        """
        facts = {
            "application_id": application_id,
            "IS_STACK_HOST": self.stack_host,
            "app_style_file": sheet_file,
            "app_style_css": css,
            "app_style_present": len(css) > 0,
            **self.state,
        }
        path = (application_id, sheet_file)
        if self._holds(self.deploy, facts):
            self.files[path] = css
            self.operations.append(("write", path))
        if self._holds(self.remove, facts):
            if path in self.files:
                del self.files[path]
            self.operations.append(("remove", path))
        templar = self._templar(facts)
        for fact in STATE_FACTS:
            if fact in self.record:
                self.state[fact] = templar.template(
                    trust_as_template(self.record[fact])
                )


class TestEachSheetStateIsAppliedOncePerPath(unittest.TestCase):
    def setUp(self) -> None:
        self.replay = Replay(TASKS, CORE, VARS, stack_host=True)

    def test_sibling_vhosts_without_a_sheet_remove_it_once(self) -> None:
        for _ in range(3):
            self.replay.vhost(WORDPRESS, CLEAR, "")
        self.assertEqual(self.replay.operations, [("remove", (WORDPRESS, CLEAR))])

    def test_an_identical_render_on_one_path_is_written_once(self) -> None:
        self.replay.vhost(MATRIX, CLEAR, "body{}")
        self.replay.vhost(MATRIX, CLEAR, "body{}")
        self.assertEqual(self.replay.operations, [("write", (MATRIX, CLEAR))])
        self.assertEqual(self.replay.files, {(MATRIX, CLEAR): "body{}"})

    def test_a_differing_render_on_one_path_is_written_and_the_last_wins(
        self,
    ) -> None:
        self.replay.vhost(MATRIX, CLEAR, "a{}")
        self.replay.vhost(MATRIX, CLEAR, "b{}")
        self.assertEqual(
            self.replay.operations,
            [("write", (MATRIX, CLEAR)), ("write", (MATRIX, CLEAR))],
        )
        self.assertEqual(self.replay.files, {(MATRIX, CLEAR): "b{}"})

    def test_a_sheet_that_disappears_and_returns_is_removed_and_rewritten(
        self,
    ) -> None:
        self.replay.vhost(MATRIX, CLEAR, "a{}")
        self.replay.vhost(MATRIX, CLEAR, "")
        self.replay.vhost(MATRIX, CLEAR, "a{}")
        self.assertEqual(
            self.replay.operations,
            [
                ("write", (MATRIX, CLEAR)),
                ("remove", (MATRIX, CLEAR)),
                ("write", (MATRIX, CLEAR)),
            ],
        )
        self.assertEqual(self.replay.files, {(MATRIX, CLEAR): "a{}"})

    def test_each_network_keeps_its_own_render(self) -> None:
        for _ in range(2):
            self.replay.vhost(MATRIX, CLEAR, "clear{}")
            self.replay.vhost(MATRIX, ONION, "onion{}")
        self.assertEqual(
            self.replay.operations,
            [("write", (MATRIX, CLEAR)), ("write", (MATRIX, ONION))],
        )
        self.assertEqual(
            self.replay.files,
            {(MATRIX, CLEAR): "clear{}", (MATRIX, ONION): "onion{}"},
        )

    def test_another_role_with_the_same_sheet_name_is_written(self) -> None:
        self.replay.vhost(MATRIX, CLEAR, "body{}")
        self.replay.vhost(WORDPRESS, CLEAR, "body{}")
        self.assertEqual(
            self.replay.operations,
            [("write", (MATRIX, CLEAR)), ("write", (WORDPRESS, CLEAR))],
        )


def _position(tasks, predicate):
    positions = [index for index, task in enumerate(tasks) if predicate(task)]
    if len(positions) != 1:
        raise LookupError(f"expected one matching task, found {positions}")
    return positions[0]


class TestTheStateIsRecordedAfterTheSheetIsApplied(unittest.TestCase):
    def test_the_record_follows_the_write_and_the_removal(self) -> None:
        tasks = load_yaml_any(str(TASKS))
        write = _position(tasks, lambda task: "stack_host_copy" in task)
        removal = _position(tasks, lambda task: "ansible.builtin.file" in task)
        record = _position(
            tasks,
            lambda task: "set_fact" in task and "design_css_states" in task["set_fact"],
        )
        self.assertLess(write, record)
        self.assertLess(removal, record)


class TestAHostWithoutTheStackNeverRemoves(unittest.TestCase):
    def test_no_vhost_removes_the_sheet(self) -> None:
        replay = Replay(TASKS, CORE, VARS, stack_host=False)
        replay.vhost(WORDPRESS, CLEAR, "")
        replay.vhost(WORDPRESS, CLEAR, "")
        self.assertEqual(replay.operations, [])


if __name__ == "__main__":
    unittest.main()
