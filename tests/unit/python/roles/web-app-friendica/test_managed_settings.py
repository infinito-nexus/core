from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles/web-app-friendica"
ORIG_DEBUGGING = "{{ (lookup('debug') | bool) | lower }}"
ORIG_LOGLEVEL = "{% if lookup('debug') | bool %}9{% else %}5{% endif %}"


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def _templated(node, variables: dict, stubs: dict):
    real_get = lookup_loader.get

    def get(lookup_name, *args, **kwargs):
        if lookup_name in stubs:
            return _Stub(stubs[lookup_name])
        return real_get(lookup_name, *args, **kwargs)

    templar = Templar(loader=DataLoader(), variables=variables)
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(node)


def _forms() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})


def _sink(debug: bool) -> dict:
    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
    )
    application = {
        "services": {
            "friendica": {
                "logging": _templated(
                    declared["friendica"]["logging"], {}, {"debug": lambda: debug}
                )
            }
        }
    }
    variables = {
        **DataLoader().load_from_file(
            str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
        ),
        "application_id": "web-app-friendica",
    }
    return dict(
        _templated(
            variables["FRIENDICA_LOG_SETTINGS"],
            variables,
            {"form_values": lambda _app, form: values(form, _forms(), application, {})},
        )
    )


def _env_value(name: str, debug: bool) -> str:
    line = next(
        line
        for line in read_text(str(ROLE / "templates/env.j2")).splitlines()
        if line.startswith(f"{name}=")
    )
    rendered = _templated(
        _trust_as_template(line.removesuffix('{{"\\n"}}')),
        {"FRIENDICA_LOG_SETTINGS": _sink(debug)},
        {},
    )
    return rendered.split("=", 1)[1]


class TestLogSettings(unittest.TestCase):
    def test_the_sink_carries_both_log_settings(self):
        self.assertEqual(["debugging", "loglevel"], list(_sink(True)))

    def test_the_environment_keeps_the_old_values(self):
        for debug in (True, False):
            for name, old in (
                ("FRIENDICA_DEBUGGING", ORIG_DEBUGGING),
                ("FRIENDICA_LOGLEVEL", ORIG_LOGLEVEL),
            ):
                with self.subTest(debug=debug, name=name):
                    expected = _templated(
                        _trust_as_template(old), {}, {"debug": lambda d=debug: d}
                    )
                    self.assertEqual(str(expected), _env_value(name, debug))

    def test_the_environment_reads_the_log_settings_only_from_the_sink(self):
        text = read_text(str(ROLE / "templates/env.j2"))
        for sink, expected in (
            (
                {"debugging": True, "loglevel": 7},
                {"FRIENDICA_DEBUGGING": "true", "FRIENDICA_LOGLEVEL": "7"},
            ),
            (
                {"debugging": False, "loglevel": 3},
                {"FRIENDICA_DEBUGGING": "false", "FRIENDICA_LOGLEVEL": "3"},
            ),
        ):
            for name, value in expected.items():
                with self.subTest(sink=sink, name=name):
                    line = next(
                        line
                        for line in text.splitlines()
                        if line.startswith(f"{name}=")
                    )
                    self.assertEqual(
                        f"{name}={value}",
                        _templated(
                            _trust_as_template(line.removesuffix('{{"\\n"}}')),
                            {"FRIENDICA_LOG_SETTINGS": sink},
                            {"debug": self.fail},
                        ),
                    )

    def test_the_form_is_native_and_names_the_page_fields(self):
        form = _forms()["logs"]
        self.assertIs(True, form["native"])
        self.assertEqual("/admin/logs", form["path"])
        for field, spec in form["fields"].items():
            with self.subTest(field=field):
                self.assertEqual(f'[name="{field}"]', spec["selector"])
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'logs') }}",
            load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))["FRIENDICA_LOG_SETTINGS"],
        )


if __name__ == "__main__":
    unittest.main()
