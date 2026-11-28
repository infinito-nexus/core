from __future__ import annotations

import json
import re
import unittest
from types import SimpleNamespace

from ansible.parsing.dataloader import DataLoader
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from plugins.filter.dotenv import FilterModule as DotenvFilters
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_FORMS

ROLE = PROJECT_ROOT / "roles" / "web-app-mattermost"
FORMS = ROLE / ROLE_FILE_META_FORMS
CORE = ROLE / "tasks" / "00_core.yml"
ENV = ROLE / "templates" / "env.j2"
ENV_DRIFT = "tasks/utils/forms/env.yml"
STATIC_ASSIGNMENT = re.compile(r"^(MM_[A-Z0-9_]+)=", re.MULTILINE)
SECRETS = {
    "MM_EMAILSETTINGS_SMTPPASSWORD",
    "MM_GITLABSETTINGS_SECRET",
    "MM_FILESETTINGS_AMAZONS3SECRETACCESSKEY",
    "MM_FILESETTINGS_AMAZONS3ACCESSKEYID",
}


def _fields() -> dict:
    return load_yaml_any(str(FORMS))["settings"]["fields"]


def _sample() -> dict[str, str]:
    sample = dict.fromkeys(_fields(), "true")
    sample["mm_teamsettings_sitename"] = '"Infinito" Nexus # chat "'
    sample["mm_emailsettings_smtpusername"] = '"quoted"'
    sample["mm_servicesettings_siteurl"] = "https://chat.infinito.test"
    return sample


def _environment() -> Environment:
    env = Environment(
        loader=DictLoader(
            {
                "env.j2": read_text(str(ENV)),
                "roles/sys-svc-container/templates/env.j2": "",
            }
        ),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(DotenvFilters().filters())
    env.filters["bool"] = bool
    env.globals["lookup"] = lambda name, *terms: (
        SimpleNamespace(enabled=False) if name == "email" else False
    )
    return env


def _render(settings: dict) -> str:
    return (
        _environment()
        .get_template("env.j2")
        .render(
            MATTERMOST_SETTINGS=settings,
            container_port=8065,
            MATTERMOST_DATABASE_DSN="postgres://unused",
            MATTERMOST_OIDC_ENABLED=False,
            MATTERMOST_MCP_ENABLED=False,
            MATTERMOST_LOGIN_REGISTRATION=False,
            application_id="web-app-mattermost",
            DEPLOYMENT_MODE="compose",
        )
    )


def _held(content: str, fields) -> dict:
    template = _environment().from_string(
        "{{ content | dotenv_fields(fields) | tojson }}"
    )
    return json.loads(
        template.render(content=content, fields=list(fields), DEPLOYMENT_MODE="compose")
    )


class TestTheEnvFileCarriesTheSettingsForm(unittest.TestCase):
    def test_the_drift_read_takes_back_exactly_what_the_env_writes(self) -> None:
        settings = _sample()
        self.assertEqual(settings, _held(_render(settings), settings))

    def test_no_managed_setting_is_also_written_outside_the_form(self) -> None:
        static = set(STATIC_ASSIGNMENT.findall(read_text(str(ENV))))
        self.assertEqual(set(), static & {field.upper() for field in _fields()})

    def test_the_secrets_stay_outside_the_form(self) -> None:
        static = set(STATIC_ASSIGNMENT.findall(read_text(str(ENV))))
        self.assertLessEqual(SECRETS, static)
        self.assertEqual(set(), SECRETS & {field.upper() for field in _fields()})

    def test_every_switch_maps_to_the_string_the_env_file_holds(self) -> None:
        for field, spec in _fields().items():
            if spec["type"] == "checkbox":
                with self.subTest(field=field):
                    self.assertTrue(spec.get("map"))
                    for value in spec["map"].values():
                        self.assertIn(value, ("true", "false"))


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_env_drift_runs_before_the_stack_renders_the_env_file(self) -> None:
        tasks = DataLoader().load_from_file(str(CORE), trusted_as_template=True)
        drift = next(i for i, task in enumerate(tasks) if ENV_DRIFT in str(task))
        stack = next(
            i
            for i, task in enumerate(tasks)
            if task.get("include_role", {}).get("tasks_from") == "consumer.yml"
        )
        self.assertLess(drift, stack)
        self.assertEqual("settings", tasks[drift]["vars"]["forms_env_form"])
        self.assertIn("MATTERMOST_SETTINGS", tasks[drift]["vars"]["forms_env_fields"])


class TestMattermostLocksTheSettings(unittest.TestCase):
    def test_the_settings_form_is_native(self) -> None:
        self.assertIs(True, load_yaml_any(str(FORMS))["settings"]["native"])


if __name__ == "__main__":
    unittest.main()
