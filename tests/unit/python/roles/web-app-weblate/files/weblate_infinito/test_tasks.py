from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import types
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-weblate"
MODULE = ROLE / "files/python/weblate_infinito/tasks.py"
SWITCH = "WEBLATE_LOGIN_2FA_ENFORCED"


def matches(row, key: str, wanted) -> bool:
    field, _, lookup = key.partition("__")
    value = getattr(row, field)
    if lookup == "isnull":
        return (value is None) is wanted
    if lookup == "in":
        return value in wanted
    return value == wanted


class FakeObjects:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    def _where(self, criteria: dict, keep: bool) -> FakeObjects:
        return FakeObjects(
            [
                row
                for row in self.rows
                if all(matches(row, key, wanted) for key, wanted in criteria.items())
                is keep
            ]
        )

    def filter(self, **criteria) -> FakeObjects:
        return self._where(criteria, True)

    def exclude(self, **criteria) -> FakeObjects:
        return self._where(criteria, False)

    def all(self) -> FakeObjects:
        return self

    def values_list(self, *fields: str) -> list[tuple]:
        return [tuple(getattr(row, field) for field in fields) for row in self.rows]

    def update(self, **values) -> int:
        for row in self.rows:
            vars(row).update(values)
        return len(self.rows)


class FakeCelery:
    def __init__(self) -> None:
        self.receivers: list = []
        self.options: list[dict] = []
        self.on_after_finalize = types.SimpleNamespace(connect=self._connect)

    def _connect(self, receiver):
        self.receivers.append(receiver)
        return receiver

    def task(self, **options):
        self.options.append(options)

        def register(function):
            function.s = lambda: ("signature", function.__name__)
            return function

        return register


def team(pk: int, name: str, *, on: bool = False, project: int | None = None):
    return types.SimpleNamespace(
        pk=pk, name=name, defining_project=project, enforced_2fa=on
    )


def project(pk: int, *, on: bool = False):
    return types.SimpleNamespace(pk=pk, enforced_2fa=on)


def flags(rows: list) -> dict[int, bool]:
    return {row.pk: row.enforced_2fa for row in rows}


class WeblateTwoFactorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.marker = self.data / "infinito" / "enforced_2fa.json"
        self.teams = [
            team(1, "Users"),
            team(2, "Guests"),
            team(3, "Reviewers", on=True),
            team(4, "Administration", project=7),
        ]
        self.projects = [project(7), project(8, on=True)]
        self.celery = FakeCelery()
        stubs = {
            "django": {},
            "django.conf": {"settings": types.SimpleNamespace(DATA_DIR=str(self.data))},
            "weblate": {},
            "weblate.utils": {},
            "weblate.utils.celery": {"app": self.celery},
            "weblate.auth": {},
            "weblate.auth.models": {
                "Group": types.SimpleNamespace(objects=FakeObjects(self.teams))
            },
            "weblate.trans": {},
            "weblate.trans.models": {
                "Project": types.SimpleNamespace(objects=FakeObjects(self.projects))
            },
        }
        modules = {}
        for name, attrs in stubs.items():
            modules[name] = types.ModuleType(name)
            vars(modules[name]).update(attrs)
        self.enterContext(mock.patch.dict("sys.modules", modules))
        namespace = {"__name__": "weblate_infinito.tasks"}
        exec(compile(read_text(str(MODULE)), str(MODULE), "exec"), namespace)
        self.tasks = types.SimpleNamespace(**namespace)

    def deploy(self, enforced: str) -> str:
        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, {SWITCH: enforced}),
            contextlib.redirect_stdout(stdout),
        ):
            self.tasks.main()
        return stdout.getvalue().strip()

    def test_enforcing_flags_every_project_and_every_team_but_guests_and_project_teams(
        self,
    ) -> None:
        self.assertEqual(self.deploy("1"), "CHANGED 2")
        self.assertEqual(flags(self.teams), {1: True, 2: False, 3: True, 4: False})
        self.assertEqual(flags(self.projects), {7: True, 8: True})

    def test_the_marker_owns_only_what_the_deploy_switched_on(self) -> None:
        self.deploy("1")
        self.assertEqual(
            json.loads(self.marker.read_text()),  # nocheck: cache-read tempdir
            {"projects": [7], "teams": [1]},
        )

    def test_a_converged_site_switches_nothing_and_rewrites_no_marker(self) -> None:
        self.deploy("1")
        with mock.patch.object(
            Path, "replace", side_effect=AssertionError("the marker was rewritten")
        ):
            self.assertEqual(self.deploy("1"), "CHANGED 0")

    def test_lifting_clears_only_the_flags_the_deploy_set(self) -> None:
        self.deploy("1")
        self.assertEqual(self.deploy("0"), "CHANGED 2")
        self.assertEqual(flags(self.teams), {1: False, 2: False, 3: True, 4: False})
        self.assertEqual(flags(self.projects), {7: False, 8: True})
        self.assertEqual(
            json.loads(self.marker.read_text()),  # nocheck: cache-read tempdir
            {"projects": [], "teams": []},
        )

    def test_an_unknown_switch_value_lifts_nothing(self) -> None:
        self.deploy("1")
        with self.assertRaises(KeyError):
            self.deploy("true")
        self.assertEqual(flags(self.projects), {7: True, 8: True})

    def test_the_worker_reconverges_every_hour(self) -> None:
        self.deploy("1")
        self.teams[0].enforced_2fa = False
        self.projects.append(project(9))
        sender = mock.Mock()
        for receiver in self.celery.receivers:
            receiver(sender)
        sender.add_periodic_task.assert_called_once_with(
            3600,
            ("signature", "enforce_two_factor"),
            name="infinito-enforce-two-factor",
        )
        with mock.patch.dict(os.environ, {SWITCH: "1"}):
            self.tasks.enforce_two_factor()
        self.assertTrue(self.teams[0].enforced_2fa)
        self.assertEqual(flags(self.projects), {7: True, 8: True, 9: True})
        self.assertEqual(
            json.loads(self.marker.read_text()),  # nocheck: cache-read tempdir
            {"projects": [7, 9], "teams": [1]},
        )

    def test_a_deleted_object_leaves_the_ownership(self) -> None:
        self.assertEqual(self.tasks.plan(True, {1: True}, [1, 9]), ([], True, [1]))
        self.assertEqual(self.tasks.plan(False, {1: True}, [1, 9]), ([1], False, []))


class WeblateTwoFactorDeployTests(unittest.TestCase):
    def test_every_stack_host_deploy_runs_the_convergence(self) -> None:
        core = load_yaml_str(read_text(str(ROLE / "tasks/00_core.yml")))
        (stack_host,) = [
            task
            for task in core
            for child in task.get("block", [])
            if child.get("ansible.builtin.include_tasks") == "utils/two_factor.yml"
        ]
        self.assertEqual(stack_host["when"], "IS_STACK_HOST | bool")
        (task,) = load_yaml_str(read_text(str(ROLE / "tasks/utils/two_factor.yml")))
        self.assertNotIn("when", task)
        self.assertIn(
            "weblate shell -c 'from weblate_infinito.tasks import main; main()'",
            task["ansible.builtin.shell"]["cmd"],
        )

    def test_the_module_reaches_its_mount_through_the_rendered_file(self) -> None:
        core = load_yaml_str(read_text(str(ROLE / "tasks/00_core.yml")))
        (entry,) = [
            template
            for task in core
            for template in task.get("vars", {}).get("role_templates", [])
            if template["src"].endswith("/weblate_infinito/tasks.py') }}")
        ]
        self.assertEqual(entry["dest"], "{{ WEBLATE_TWO_FACTOR_TASKS_HOST }}")
        name = "weblate_infinito_tasks.py"
        self.assertIn(
            name,
            load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))[
                "WEBLATE_TWO_FACTOR_TASKS_HOST"
            ],
        )
        self.assertIn(
            name,
            load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))[
                "two_factor_tasks"
            ]["source"],
        )


if __name__ == "__main__":
    unittest.main()
