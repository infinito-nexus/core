from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import re
import types
import unittest
from unittest.mock import patch

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TASKS_MCP,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT
from .files.test_rbac_teams import FakePretix

ROLE = PROJECT_ROOT / "roles" / "web-app-pretix"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
TEAMS_TASKS = ROLE / "tasks" / "utils" / "rbac_teams.yml"
MCP_TASKS = ROLE / ROLE_FILE_TASKS_MCP
RBAC_SCRIPT = ROLE / "files" / "python" / "rbac_teams.py"
MCP_SCRIPT = ROLE / "files" / "python" / "provision_mcp_identity.py"
READ = ROLE / "files" / "sql" / "select-teams.sql"
LOADER = ROLE / "templates" / "javascript.js.j2"
SHARED_RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
DRIFT = "tasks/utils/forms/drift.yml"
SYNC = "tasks/utils/rbac/sync.yml"
SINKS = {
    "team_organizers": "PRETIX_TEAM_ORGANIZERS",
    "team_checkin": "PRETIX_TEAM_CHECKIN",
    "team_mcp": "PRETIX_TEAM_MCP",
}
ENFORCED = ("team_organizers", "team_checkin")
JSON_KEY = re.compile(r"'(\w+)',\s*team\.\w+")
EXPECTED = {
    "team_organizers": {
        "all_events": True,
        "all_event_permissions": True,
        "limit_event_permissions": {},
        "all_organizer_permissions": True,
        "limit_organizer_permissions": {},
    },
    "team_checkin": {
        "all_events": True,
        "all_event_permissions": False,
        "limit_event_permissions": {"event.orders:checkin": True},
        "all_organizer_permissions": False,
        "limit_organizer_permissions": {},
    },
    "team_mcp": {
        "all_events": True,
        "all_event_permissions": False,
        "limit_event_permissions": {"event.orders:read": True},
        "all_organizer_permissions": False,
        "limit_organizer_permissions": {},
    },
}


def _forms() -> dict:
    return load_yaml_any(str(FORMS))


def _managed() -> tuple:
    tree = ast.parse(read_text(str(RBAC_SCRIPT)))
    return next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(target, "id", None) == "MANAGED" for target in node.targets)
    )


def _tasks(path) -> list[dict]:
    return DataLoader().load_from_file(str(path), trusted_as_template=True)


def _steps(path) -> list[dict]:
    """Args:
    path: a task file whose blocks hold no condition of their own children.

    Returns:
    the tasks in run order, each block child carrying the condition of its block.
    """
    return [
        {**step, "when": task["when"]} if "block" in task else step
        for task in _tasks(path)
        for step in task.get("block", [task])
    ]


def _render(expression, variables: dict):
    return Templar(loader=DataLoader(), variables=variables).template(expression)


def _application() -> dict:
    services = load_yaml_any(str(SERVICES))
    return {
        "forms": _forms(),
        "services": {
            "sso": {"enabled": True},
            "pretixmcp": {"enabled": True},
            "pretix": {"teams": services["pretix"]["teams"]},
        },
    }


def _include_index(tasks: list[dict], path: str) -> int:
    return next(
        index
        for index, task in enumerate(tasks)
        if path in str(task.get("ansible.builtin.include_tasks", ""))
    )


class FakeMcpPretix:
    def __init__(self) -> None:
        self.teams = []
        self.tokens = []

    def modules(self, organizer: object) -> dict:
        backend = self

        def get_or_create(organizer, name, defaults):
            team = types.SimpleNamespace(organizer=organizer, name=name, **defaults)
            backend.teams.append(team)
            return team, True

        def update_or_create(team, name, defaults):
            backend.tokens.append((team, name))
            return None, True

        entries = {
            "pretix": {},
            "pretix.base": {},
            "pretix.base.models": {
                "Organizer": types.SimpleNamespace(
                    objects=types.SimpleNamespace(
                        order_by=lambda field: types.SimpleNamespace(
                            first=lambda: organizer
                        )
                    )
                )
            },
            "pretix.base.models.organizer": {
                "Team": types.SimpleNamespace(
                    objects=types.SimpleNamespace(get_or_create=get_or_create)
                ),
                "TeamAPIToken": types.SimpleNamespace(
                    objects=types.SimpleNamespace(update_or_create=update_or_create)
                ),
            },
        }
        out = {}
        for name, attrs in entries.items():
            module = types.ModuleType(name)
            for attr, value in attrs.items():
                setattr(module, attr, value)
            out[name] = module
        return out


def _exec(script, env: dict, modules: dict) -> str:
    spec = importlib.util.spec_from_file_location(script.stem, script)
    module = importlib.util.module_from_spec(spec)
    stdout = io.StringIO()
    with (
        patch.dict("os.environ", env),
        patch.dict("sys.modules", modules),
        contextlib.redirect_stdout(stdout),
    ):
        spec.loader.exec_module(module)
    return stdout.getvalue()


class TestTheFormsFileDeclaresTheManagedTeams(unittest.TestCase):
    def test_each_team_form_names_its_sink_and_the_sink_reads_only_that_form(self):
        sinks = load_yaml_any(str(VARS))
        for form, sink in SINKS.items():
            with self.subTest(form=form):
                self.assertEqual([sink], _forms()[form]["sinks"])
                self.assertEqual(
                    f"{{{{ lookup('form_values', application_id, '{form}') }}}}",
                    sinks[sink],
                )

    def test_each_form_declares_exactly_the_fields_the_converge_writes(self):
        for form in SINKS:
            with self.subTest(form=form):
                self.assertEqual(set(_managed()), set(_forms()[form]["fields"]))

    def test_each_form_locks_only_its_own_team_by_name(self):
        teams = load_yaml_any(str(SERVICES))["pretix"]["teams"]
        for form in SINKS:
            with self.subTest(form=form):
                record = _forms()[form]["record"]
                self.assertEqual("#id_name", record["selector"])
                key = record["source"].rsplit(".", 2)[-2]
                self.assertEqual(f"services.pretix.teams.{key}.names", record["source"])
                self.assertEqual(1, len(teams[key]["names"]))

    def test_the_sso_teams_are_enforced_and_the_mcp_team_is_seeded(self):
        for form in SINKS:
            modes = {spec["mode"] for spec in _forms()[form]["fields"].values()}
            whens = {spec["when"] for spec in _forms()[form]["fields"].values()}
            with self.subTest(form=form):
                if form in ENFORCED:
                    self.assertEqual({"enforced"}, modes)
                    self.assertEqual({"services.sso.enabled"}, whens)
                else:
                    self.assertEqual({"seeded"}, modes)
                    self.assertEqual({"services.pretixmcp.enabled"}, whens)

    def test_the_forms_carry_the_permissions_the_role_wrote_before(self):
        application = _application()
        for form, expected in EXPECTED.items():
            with self.subTest(form=form):
                self.assertEqual(
                    expected, values(form, application["forms"], application, {})
                )

    def test_the_lock_renderer_is_loaded_on_every_page(self):
        services = load_yaml_any(str(SERVICES))
        self.assertIs(True, services["javascript"]["enabled"])
        self.assertIn(SHARED_RENDERER, read_text(str(LOADER)))


class TestTheConvergeTakesTheTeamsFromTheSinks(unittest.TestCase):
    def test_the_rbac_teams_combine_each_enforced_sink_with_name_and_group(self):
        teams = load_yaml_any(str(VARS))["PRETIX_RBAC_TEAMS"]
        self.assertEqual(len(ENFORCED), len(teams))
        for form, item in zip(ENFORCED, teams, strict=True):
            with self.subTest(form=form):
                self.assertTrue(
                    item.lstrip().startswith(f"{{{{ {SINKS[form]} | combine(")
                )
                self.assertIn(f"PRETIX_TEAM_NAMES.{form}", item)

    def test_the_script_writes_every_managed_field_from_the_spec(self):
        backend = FakePretix(["acme"])
        spec = {
            "name": "Organizers (SSO)",
            "group": "/roles/web-app-pretix/organizer",
            "all_events": False,
            "all_event_permissions": True,
            "limit_event_permissions": {},
            "all_organizer_permissions": False,
            "limit_organizer_permissions": {"organizer.teams:write": True},
        }
        _exec(
            RBAC_SCRIPT,
            {
                "RBAC_CLAIM": "groups",
                "RBAC_TEAMS": json.dumps([spec]),
                "ORGANIZER_NAME": "Acme",
                "ORGANIZER_SLUG": "acme",
            },
            backend.modules(),
        )
        team = backend.team("acme", "Organizers (SSO)")
        for key in _managed():
            with self.subTest(field=key):
                self.assertEqual(spec[key], getattr(team, key))

    def test_the_mcp_team_starts_with_the_defaults_of_its_form(self):
        backend = FakeMcpPretix()
        organizer = types.SimpleNamespace(slug="acme")
        defaults = {
            **EXPECTED["team_mcp"],
            "all_events": False,
            "limit_event_permissions": {"event.vouchers:read": True},
        }
        _exec(
            MCP_SCRIPT,
            {
                "MCP_TEAM": "mcp-readonly",
                "MCP_TEAM_DEFAULTS": json.dumps(defaults),
                "MCP_TOKEN": "synthetic-token-value",
            },
            backend.modules(organizer),
        )
        (team,) = backend.teams
        for key, value in defaults.items():
            with self.subTest(field=key):
                self.assertEqual(value, getattr(team, key))

    def test_the_mcp_task_hands_the_seeded_sink_to_the_script(self):
        task = next(
            task for task in _tasks(MCP_TASKS) if "ansible.builtin.shell" in task
        )
        self.assertIn(
            "-e MCP_TEAM_DEFAULTS={{ PRETIX_TEAM_MCP | to_json | quote }}",
            task["ansible.builtin.shell"]["cmd"],
        )


class TestTheDeployReportsBeforeItConverges(unittest.TestCase):
    def test_the_teams_are_read_and_reported_before_the_sync(self):
        tasks = _steps(TEAMS_TASKS)
        read = next(
            index
            for index, task in enumerate(tasks)
            if str(task.get("database_query", {}).get("query_file", "")).find(READ.name)
            != -1
        )
        report = _include_index(tasks, DRIFT)
        sync = _include_index(tasks, SYNC)
        self.assertLess(read, report)
        self.assertLess(report, sync)
        for index in (read, report):
            with self.subTest(task=index):
                self.assertEqual("PRETIX_OIDC_ENABLED | bool", tasks[index]["when"])

    def test_the_read_selects_exactly_the_managed_fields_of_the_named_teams(self):
        text = read_text(str(READ))
        self.assertEqual(set(_managed()), set(JSON_KEY.findall(text)))
        self.assertIn("%(names)s", text)
        names = load_yaml_any(str(VARS))["PRETIX_TEAM_NAMES"]
        self.assertEqual(set(ENFORCED), set(names))
        for form in ENFORCED:
            key = form.removeprefix("team_")
            with self.subTest(form=form):
                self.assertIn(f"services.pretix.teams.{key}.names", names[form])

    def test_the_report_reads_what_the_store_returned(self):
        tasks = _steps(TEAMS_TASKS)
        report = tasks[_include_index(tasks, DRIFT)]
        stored = {"team_checkin": EXPECTED["team_checkin"]}
        for rows, current in (([[json.dumps(stored)]], stored), ([["{}"]], {})):
            with self.subTest(current=current):
                self.assertEqual(
                    current,
                    _render(
                        report["vars"]["forms_drift_current"],
                        {"pretix_teams_stored": {"rows": rows}},
                    ),
                )


if __name__ == "__main__":
    unittest.main()
