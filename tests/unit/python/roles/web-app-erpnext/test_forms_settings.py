from __future__ import annotations

import io
import json
import os
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.applications.forms import locks
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-erpnext"
LOGIN_SCRIPT = ROLE / "files" / "python" / "apply" / "login" / "methods.py"
LOGIN_TASKS = ROLE / "tasks" / "01_manager_ops.yml"
DESIGN_SCRIPT = ROLE / "files" / "python" / "apply" / "design_settings.py"
DESIGN_TASKS = ROLE / "tasks" / "05_design.yml"
DESIGN_CALL = ROLE / "tasks" / "utils" / "design_settings.yml"
ROUNDING_TASKS = ROLE / "tasks" / "06_rounding.yml"
ROUNDING_CALL = ROLE / "tasks" / "utils" / "rounding.yml"
DRIFT = "tasks/utils/forms/drift.yml"
SHARED_RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
DOCTYPES = {
    "system_settings": "System Settings",
    "system_rounding": "System Settings",
    "accounts_rounding": "Accounts Settings",
    "website_settings": "Website Settings",
    "branding": "Website Settings",
}
SINKS = {
    "system_settings": "ERPNEXT_SYSTEM_SETTINGS",
    "system_rounding": "ERPNEXT_SYSTEM_ROUNDING",
    "accounts_rounding": "ERPNEXT_ACCOUNTS_ROUNDING",
    "website_settings": "ERPNEXT_WEBSITE_SETTINGS",
    "branding": "ERPNEXT_BRANDING",
}
ENVIRONMENT = {
    "SYSTEM_SETTINGS": "ERPNEXT_SYSTEM_SETTINGS",
    "WEBSITE_SETTINGS": "ERPNEXT_WEBSITE_SETTINGS",
}
ROUNDING_ENVIRONMENT = {
    "SYSTEM_ROUNDING": "ERPNEXT_SYSTEM_ROUNDING",
    "ACCOUNTS_ROUNDING": "ERPNEXT_ACCOUNTS_ROUNDING",
}
ROUNDING_FIELDS = {
    "system_rounding": "rounding_method",
    "accounts_rounding": "round_row_wise_tax",
}
INPUT_TAGS = {"select": "select"}


def _forms() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS))


def _application(native: bool, email: bool, second: bool, registration: bool):
    return {
        "forms": _forms(),
        "services": {
            "erpnext": {
                "login": {
                    "method": {
                        "native": {"enabled": native},
                        "email": {"enabled": email},
                        "2fa": {"enabled": second},
                        "registration": {"enabled": registration},
                    }
                },
            },
        },
    }


def _rounding_application(rounding: dict) -> dict:
    application = _application(True, False, True, False)
    application["services"]["erpnext"]["rounding"] = rounding
    application["services"]["design"] = {"enabled": False}
    return application


def _design_application(design: bool, title) -> dict:
    return {
        "forms": _forms(),
        "services": {
            "design": {"enabled": design},
            "erpnext": {"title": title},
        },
    }


class _Store:
    def __init__(self, singles: dict) -> None:
        self.singles = singles
        self.writes: list[tuple] = []

    def get_single_value(self, doctype: str, field: str):
        return self.singles[(doctype, field)]

    def set_single_value(self, doctype: str, field: str, value) -> None:
        self.writes.append((doctype, field, value))
        self.singles[(doctype, field)] = value


def _frappe(store: _Store) -> mock.MagicMock:
    frappe = mock.MagicMock()
    frappe.db.get_single_value.side_effect = store.get_single_value
    frappe.db.set_single_value.side_effect = store.set_single_value
    frappe.db.get_value.return_value = 0
    return frappe


def _run(script: Path, frappe: mock.MagicMock, environment: dict) -> str:
    modules = {
        "frappe": frappe,
        "frappe.installer": frappe.installer,
        "frappe.website": frappe.website,
        "frappe.website.utils": frappe.website.utils,
    }
    out = io.StringIO()
    with (
        mock.patch.dict(sys.modules, modules),
        mock.patch.dict(os.environ, environment),
        redirect_stdout(out),
    ):
        runpy.run_path(str(script))
    return out.getvalue()


def _environment(mode: str) -> dict:
    return {
        "SITE_NAME": "site",
        "LOGIN_MODE": mode,
        "SYSTEM_SETTINGS": json.dumps(
            {
                "login_with_email_link": 0,
                "enable_two_factor_auth": 1,
                "disable_user_pass_login": 1,
            }
        ),
        "WEBSITE_SETTINGS": json.dumps({"disable_signup": 1}),
        "LOGIN_2FA": "true",
        "LOGIN_2FA_ENFORCED": "false",
    }


def _design_environment(mode: str, branding: dict) -> dict:
    return {
        "SITE_NAME": "site",
        "DESIGN_MODE": mode,
        "BRANDING": json.dumps(branding),
        "DESIGN_LOGO_URL": "",
        "DESIGN_FAVICON_URL": "",
        "DESIGN_THEME_CSS": "",
    }


def _tasks(path: Path) -> list[dict]:
    return DataLoader().load_from_file(str(path), trusted_as_template=True)


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _mode(task: dict):
    return task.get("environment", {}).get("LOGIN_MODE")


def _reports(task: dict) -> bool:
    return DRIFT in str(task.get("ansible.builtin.include_tasks", ""))


class TestTheSinksCarryTheStoredValues(unittest.TestCase):
    def test_each_login_method_turns_into_the_flag_erpnext_stores(self) -> None:
        for native, email, second, registration in (
            (True, False, True, False),
            (False, True, False, True),
        ):
            with self.subTest(native=native, registration=registration):
                application = _application(native, email, second, registration)
                self.assertEqual(
                    {
                        "login_with_email_link": int(email),
                        "enable_two_factor_auth": int(second),
                        "disable_user_pass_login": int(not native),
                    },
                    values("system_settings", _forms(), application, {}),
                )
                self.assertEqual(
                    {"disable_signup": int(not registration)},
                    values("website_settings", _forms(), application, {}),
                )

    def test_the_title_is_managed_only_while_the_design_and_its_title_are_on(
        self,
    ) -> None:
        for design, title, branding in (
            (True, "ERP", {"app_name": "ERP", "title_prefix": "ERP"}),
            (True, False, {}),
            (False, "ERP", {}),
        ):
            with self.subTest(design=design, title=title):
                self.assertEqual(
                    branding,
                    values(
                        "branding",
                        _forms(),
                        _design_application(design, title),
                        {},
                    ),
                )

    def test_every_selector_names_its_doctype_and_field(self) -> None:
        for form, block in _forms().items():
            self.assertEqual([SINKS[form]], block["sinks"])
            self.assertEqual(
                f"/app/{DOCTYPES[form].lower().replace(' ', '-')}", block["path"]
            )
            for field, spec in block["fields"].items():
                with self.subTest(form=form, field=field):
                    tag = INPUT_TAGS.get(spec.get("type"), "input")
                    self.assertEqual(
                        f'{tag}[data-doctype="{DOCTYPES[form]}"]'
                        f'[data-fieldname="{field}"]',
                        spec["selector"],
                    )

    def test_the_sinks_read_only_their_forms(self) -> None:
        definitions = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        for form, sink in SINKS.items():
            with self.subTest(sink=sink):
                self.assertEqual(
                    f"{{{{ lookup('form_values', application_id, '{form}') }}}}",
                    definitions[sink],
                )

    def test_the_renderer_locks_the_fields(self) -> None:
        services = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
        self.assertIs(True, services["javascript"]["enabled"])
        self.assertIn(
            SHARED_RENDERER,
            read_text(str(ROLE / "templates" / "javascript.js.j2")),
        )


class TestTheRoundingIsPinnedAndLocked(unittest.TestCase):
    def test_the_role_pins_bankers_rounding_and_rounds_tax_per_document(
        self,
    ) -> None:
        services = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
        application = {"forms": _forms(), "services": services}
        self.assertEqual(
            {"rounding_method": "Banker's Rounding"},
            values("system_rounding", _forms(), application, {}),
        )
        self.assertEqual(
            {"round_row_wise_tax": 0},
            values("accounts_rounding", _forms(), application, {}),
        )

    def test_an_inventory_override_reaches_the_value_erpnext_stores(self) -> None:
        application = _rounding_application(
            {"method": "Commercial Rounding", "row_wise_tax": True}
        )
        self.assertEqual(
            {"rounding_method": "Commercial Rounding"},
            values("system_rounding", _forms(), application, {}),
        )
        self.assertEqual(
            {"round_row_wise_tax": 1},
            values("accounts_rounding", _forms(), application, {}),
        )

    def test_the_renderer_locks_both_fields_with_their_inventory_path(self) -> None:
        application = _rounding_application(
            {"method": "Banker's Rounding", "row_wise_tax": False}
        )
        locked = {
            entry["selector"]: entry
            for entry in locks(ROLE.name, _forms(), application, {}, {})
        }
        for form, field in ROUNDING_FIELDS.items():
            with self.subTest(form=form):
                block = _forms()[form]
                spec = block["fields"][field]
                self.assertEqual("enforced", spec["mode"])
                entry = locked[spec["selector"]]
                self.assertEqual(block["path"], entry["page"])
                self.assertEqual(
                    f"applications.{ROLE.name}.{spec['source']}", entry["path"]
                )
                self.assertFalse(entry["secret"])

    def test_the_pinned_method_is_one_frappe_offers(self) -> None:
        services = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
        spec = _forms()["system_rounding"]["fields"]["rounding_method"]
        self.assertIn(services["erpnext"]["rounding"]["method"], spec["enum"])


class TestTheLoginScript(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _Store(
            {
                ("System Settings", "login_with_email_link"): 1,
                ("System Settings", "enable_two_factor_auth"): 1,
                ("System Settings", "disable_user_pass_login"): 0,
                ("Website Settings", "disable_signup"): 0,
            }
        )
        self.frappe = _frappe(self.store)

    def test_read_prints_the_stored_fields_of_the_sinks_and_writes_nothing(
        self,
    ) -> None:
        out = _run(LOGIN_SCRIPT, self.frappe, _environment("read"))
        self.assertEqual(
            {
                "system_settings": {
                    "login_with_email_link": 1,
                    "enable_two_factor_auth": 1,
                    "disable_user_pass_login": 0,
                },
                "website_settings": {"disable_signup": 0},
            },
            json.loads(out.strip().splitlines()[-1]),
        )
        self.assertEqual([], self.store.writes)
        self.frappe.get_doc.assert_not_called()
        self.frappe.db.set_value.assert_not_called()
        self.frappe.db.commit.assert_not_called()

    def test_converge_writes_exactly_the_sinks(self) -> None:
        _run(LOGIN_SCRIPT, self.frappe, _environment("converge"))
        self.frappe.get_doc.assert_called_once_with("System Settings")
        self.frappe.get_doc.return_value.update.assert_called_once_with(
            {
                "login_with_email_link": 0,
                "enable_two_factor_auth": 1,
                "disable_user_pass_login": 1,
            }
        )
        self.frappe.get_doc.return_value.save.assert_called_once_with()
        self.assertEqual([("Website Settings", "disable_signup", 1)], self.store.writes)
        self.frappe.db.commit.assert_called_once_with()

    def test_an_unknown_mode_fails_before_frappe_starts(self) -> None:
        with self.assertRaises(ValueError):
            _run(LOGIN_SCRIPT, self.frappe, _environment("write"))
        self.frappe.init.assert_not_called()


class TestTheDesignScript(unittest.TestCase):
    def setUp(self) -> None:
        site = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = _Store(
            {
                ("Website Settings", "app_name"): "Admin Edit",
                ("Website Settings", "title_prefix"): "ERP",
                ("Website Settings", "head_html"): "",
            }
        )
        self.frappe = _frappe(self.store)
        self.frappe.db.get_default.return_value = "{}"
        self.frappe.get_file_json.return_value = {}
        self.frappe.get_site_path.side_effect = lambda *parts: str(
            site.joinpath(*parts)
        )

    def test_read_prints_the_stored_branding_and_writes_nothing(self) -> None:
        out = _run(
            DESIGN_SCRIPT,
            self.frappe,
            _design_environment("read", {"app_name": "ERP", "title_prefix": "ERP"}),
        )
        self.assertEqual(
            {"branding": {"app_name": "Admin Edit", "title_prefix": "ERP"}},
            json.loads(out.strip().splitlines()[-1]),
        )
        self.assertEqual([], self.store.writes)
        self.frappe.db.set_default.assert_not_called()
        self.frappe.db.commit.assert_not_called()

    def test_converge_writes_the_branding_sink(self) -> None:
        out = _run(
            DESIGN_SCRIPT,
            self.frappe,
            _design_environment("converge", {"app_name": "ERP", "title_prefix": "ERP"}),
        )
        self.assertEqual([("Website Settings", "app_name", "ERP")], self.store.writes)
        self.assertIn("DESIGN_CHANGED", out)

    def test_a_title_the_sink_drops_is_handed_back(self) -> None:
        self.frappe.db.get_default.return_value = json.dumps(
            {"Website Settings::title_prefix": {"previous": "Before", "applied": "ERP"}}
        )
        _run(DESIGN_SCRIPT, self.frappe, _design_environment("converge", {}))
        self.assertEqual(
            [("Website Settings", "title_prefix", "Before")], self.store.writes
        )

    def test_an_unknown_mode_fails_before_frappe_starts(self) -> None:
        with self.assertRaises(ValueError):
            _run(DESIGN_SCRIPT, self.frappe, _design_environment("write", {}))
        self.frappe.init.assert_not_called()


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_login_settings_are_read_and_reported_before_the_write(self) -> None:
        tasks = _tasks(LOGIN_TASKS)
        read = _index(tasks, lambda task: _mode(task) == "read")
        report = _index(tasks, _reports)
        write = _index(tasks, lambda task: _mode(task) == "converge")
        self.assertLess(read, report)
        self.assertLess(report, write)
        for index in (read, write):
            task = tasks[index]
            for name, sink in ENVIRONMENT.items():
                with self.subTest(task=task["name"], name=name):
                    self.assertIn(f"-e {name}", task["ansible.builtin.shell"]["cmd"])
                    templar = Templar(loader=DataLoader(), variables={sink: {"x": 1}})
                    self.assertEqual(
                        {"x": 1},
                        json.loads(templar.template(task["environment"][name])),
                    )

    def test_the_report_reads_the_last_line_the_read_printed(self) -> None:
        tasks = _tasks(LOGIN_TASKS)
        read = tasks[_index(tasks, lambda task: _mode(task) == "read")]
        report = tasks[_index(tasks, _reports)]
        templar = Templar(
            loader=DataLoader(),
            variables={
                read["register"]: {
                    "stdout_lines": ["noise", '{"system_settings": {"x": 1}}'],
                }
            },
        )
        self.assertEqual(
            {"system_settings": {"x": 1}},
            templar.template(report["vars"]["forms_drift_current"]),
        )

    def test_the_branding_is_read_and_reported_before_the_write(self) -> None:
        tasks = _tasks(DESIGN_TASKS)
        modes = [task.get("vars", {}).get("erpnext_design_mode") for task in tasks]
        report = _index(tasks, _reports)
        self.assertLess(modes.index("read"), report)
        self.assertLess(report, modes.index("converge"))
        for mode in ("read", "converge"):
            self.assertEqual(
                "utils/design_settings.yml",
                tasks[modes.index(mode)]["ansible.builtin.include_tasks"],
            )

    def test_both_design_modes_hand_the_branding_sink_to_the_script(self) -> None:
        (task,) = _tasks(DESIGN_CALL)
        for name in ("DESIGN_MODE", "BRANDING"):
            self.assertIn(f"-e {name}", task["ansible.builtin.shell"]["cmd"])
        for mode in ("read", "converge"):
            with self.subTest(mode=mode):
                templar = Templar(
                    loader=DataLoader(),
                    variables={
                        "ERPNEXT_BRANDING": {"x": 1},
                        "erpnext_design_mode": mode,
                    },
                )
                environment = task["environment"]
                self.assertEqual(mode, templar.template(environment["DESIGN_MODE"]))
                self.assertEqual(
                    {"x": 1}, json.loads(templar.template(environment["BRANDING"]))
                )

    def test_every_deploy_pins_the_rounding(self) -> None:
        tasks = _tasks(LOGIN_TASKS)
        (task,) = [
            task for task in tasks if task.get("include_tasks") == ROUNDING_TASKS.name
        ]
        self.assertNotIn("when", task)

    def test_the_rounding_is_read_and_reported_before_the_write(self) -> None:
        tasks = _tasks(ROUNDING_TASKS)
        modes = [task.get("vars", {}).get("erpnext_rounding_mode") for task in tasks]
        report = _index(tasks, _reports)
        self.assertLess(modes.index("read"), report)
        self.assertLess(report, modes.index("converge"))
        for mode in ("read", "converge"):
            self.assertEqual(
                "utils/rounding.yml",
                tasks[modes.index(mode)]["ansible.builtin.include_tasks"],
            )

    def test_both_rounding_modes_hand_the_sinks_to_the_script(self) -> None:
        (task,) = _tasks(ROUNDING_CALL)
        shell = task["ansible.builtin.shell"]
        self.assertIn("/files/python/apply/rounding.py", shell["stdin"])
        for name, sink in ROUNDING_ENVIRONMENT.items():
            with self.subTest(name=name):
                self.assertIn(f"-e {name}", shell["cmd"])
                templar = Templar(loader=DataLoader(), variables={sink: {"x": 1}})
                self.assertEqual(
                    {"x": 1}, json.loads(templar.template(task["environment"][name]))
                )
        for mode in ("read", "converge"):
            with self.subTest(mode=mode):
                templar = Templar(
                    loader=DataLoader(), variables={"erpnext_rounding_mode": mode}
                )
                self.assertEqual(
                    mode, templar.template(task["environment"]["ROUNDING_MODE"])
                )

    def test_only_a_converge_that_wrote_reports_a_change(self) -> None:
        (task,) = _tasks(ROUNDING_CALL)
        for mode, printed, changed in (
            ("converge", '{"changed": ["System Settings::rounding_method"]}', True),
            ("converge", '{"changed": []}', False),
            ("read", '{"system_rounding": {"rounding_method": "x"}}', False),
        ):
            with self.subTest(mode=mode, printed=printed):
                templar = Templar(
                    loader=DataLoader(),
                    variables={
                        "erpnext_rounding_mode": mode,
                        task["register"]: {"stdout_lines": ["noise", printed]},
                    },
                )
                self.assertIs(
                    changed, templar.evaluate_conditional(task["changed_when"])
                )

    def test_the_rounding_report_reads_the_last_line_the_read_printed(self) -> None:
        (call,) = _tasks(ROUNDING_CALL)
        tasks = _tasks(ROUNDING_TASKS)
        report = tasks[_index(tasks, _reports)]
        templar = Templar(
            loader=DataLoader(),
            variables={
                call["register"]: {
                    "stdout_lines": ["noise", '{"accounts_rounding": {"x": 1}}'],
                }
            },
        )
        self.assertEqual(
            {"accounts_rounding": {"x": 1}},
            templar.template(report["vars"]["forms_drift_current"]),
        )

    def test_the_branding_report_reads_the_last_line_the_read_printed(self) -> None:
        (call,) = _tasks(DESIGN_CALL)
        tasks = _tasks(DESIGN_TASKS)
        report = tasks[_index(tasks, _reports)]
        templar = Templar(
            loader=DataLoader(),
            variables={
                call["register"]: {
                    "stdout_lines": ["noise", '{"branding": {"x": 1}}'],
                }
            },
        )
        self.assertEqual(
            {"branding": {"x": 1}},
            templar.template(report["vars"]["forms_drift_current"]),
        )


if __name__ == "__main__":
    unittest.main()
