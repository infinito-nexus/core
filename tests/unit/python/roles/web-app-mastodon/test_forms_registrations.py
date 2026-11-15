from __future__ import annotations

import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import DictLoader, Environment, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles" / "web-app-mastodon"
TASKS = ROLE / "tasks" / "07_login_methods.yml"
LOADER = ROLE / "templates" / "javascript.js.j2"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
SINK = "MASTODON_REGISTRATIONS"
DRIFT = "tasks/utils/forms/drift.yml"
RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
RENDERER_STUB = "/* shared field lock */"
HIDER = "data-infinito-2fa-enrollment"


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _is_report(task: dict) -> bool:
    return DRIFT in str(task.get("ansible.builtin.include_tasks", ""))


def _is_write(task: dict) -> bool:
    return "registrations_mode.rb" in str(task.get("args", {}).get("stdin", ""))


def _render(**variables):
    return Templar(loader=DataLoader(), variables=variables)


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_store_is_read_and_reported_before_the_write(self) -> None:
        tasks = _tasks()
        read = _index(tasks, lambda task: "database_query" in task)
        report = _index(tasks, _is_report)
        write = _index(tasks, _is_write)
        self.assertLess(read, report)
        self.assertLess(report, write)

    def test_the_read_asks_for_exactly_the_sink_fields(self) -> None:
        read = next(task for task in _tasks() if "database_query" in task)
        templar = _render(**{SINK: {"registrations_mode": "open"}})
        self.assertEqual(
            ["registrations_mode"],
            json.loads(
                templar.template(read["database_query"]["named_args"]["fields"])
            ),
        )

    def test_the_report_reads_the_yaml_mastodon_stores(self) -> None:
        expression = next(task for task in _tasks() if _is_report(task))["vars"][
            "forms_drift_current"
        ]["registrations"]
        for rows, current in (
            (
                [["registrations_mode", "--- approved\n"]],
                {"registrations_mode": "approved"},
            ),
            ([], {}),
        ):
            with self.subTest(rows=rows):
                templar = _render(mastodon_registrations_stored={"rows": rows})
                self.assertEqual(current, templar.template(expression))

    def test_the_write_takes_the_mode_from_the_sink(self) -> None:
        write = next(task for task in _tasks() if _is_write(task))
        templar = _render(
            **{SINK: {"registrations_mode": "approved"}}, MASTODON_LOCAL_CID="cid"
        )
        self.assertIn(
            "-e MASTODON_REGISTRATIONS_MODE=approved",
            templar.template(write["ansible.builtin.shell"]),
        )


class TestTheFormMapsTheRegistrationSwitch(unittest.TestCase):
    def test_the_switch_maps_to_the_modes_mastodon_stores(self) -> None:
        forms = load_yaml_any(str(FORMS))
        for enabled, mode in ((True, "open"), (False, "none")):
            with self.subTest(enabled=enabled):
                application = {
                    "services": {
                        "mastodon": {
                            "login": {"method": {"registration": {"enabled": enabled}}}
                        }
                    }
                }
                self.assertEqual(
                    {"registrations_mode": mode},
                    values("registrations", forms, application, {}),
                )


class TestTheLoaderAlwaysLocks(unittest.TestCase):
    def _loader(self, second_factor: bool) -> str:
        env = Environment(
            loader=DictLoader(
                {
                    LOADER.name: read_text(str(LOADER)),
                    RENDERER: RENDERER_STUB,
                }
            ),
            autoescape=select_autoescape(),
        )
        env.filters["bool"] = bool
        return env.get_template(LOADER.name).render(MASTODON_LOGIN_2FA=second_factor)

    def test_the_lock_is_rendered_with_and_without_the_second_factor(self) -> None:
        for second_factor in (False, True):
            with self.subTest(second_factor=second_factor):
                self.assertIn(RENDERER_STUB, self._loader(second_factor))

    def test_the_enrollment_hider_follows_the_second_factor(self) -> None:
        self.assertIn(HIDER, self._loader(False))
        self.assertNotIn(HIDER, self._loader(True))

    def test_the_javascript_service_is_on_literally(self) -> None:
        services = load_yaml_any(str(SERVICES))
        self.assertIs(True, services["javascript"]["enabled"])


if __name__ == "__main__":
    unittest.main()
