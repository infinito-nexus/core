from __future__ import annotations

import re
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from plugins.filter.dotenv import dotenv_fields, dotenv_names
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.applications.forms import locks
from utils.templating.ansible import _trust_as_template

APPLICATION = "web-app-pihole"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
FORMS = ROLE / "meta" / "forms.yml"
SERVICES = ROLE / "meta" / "services.yml"
VARS = ROLE / "vars" / "main.yml"
ENV = ROLE / "templates" / "env.j2"
STAGE = ROLE / "tasks" / "utils" / "stack" / "stage.yml"
ENV_DRIFT = "tasks/utils/forms/env.yml"
DOMAIN = "pihole.example.test"
WEBHOME = "/admin/"
ADMIN_VALUE = "admin-value-0"
USERS = {"platform_administrator": {"password": ADMIN_VALUE}}
WEBSERVER = {"domain": DOMAIN, "webhome": WEBHOME}
FTLCONF = re.compile(r"^(FTLCONF_\w+)=(.*)$", re.MULTILINE)


class _Domain(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if list(terms) != [APPLICATION]:
            raise AssertionError(f"read {terms}, not {APPLICATION}")
        return [DOMAIN]


def _forms() -> dict:
    return load_yaml_any(str(FORMS), default_if_missing={})


def _application(sso: bool) -> dict:
    return {
        "services": {
            "sso": {"enabled": sso},
            "pihole": {"webserver": WEBSERVER},
        }
    }


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _env_lines(webserver: dict, login: dict) -> dict:
    variables = load_yaml_any(str(VARS))
    derived = {
        "PIHOLE_PASSWORD": _render(variables["PIHOLE_PASSWORD"], PIHOLE_LOGIN=login),
        "PIHOLE_WEBHOME": _render(
            variables["PIHOLE_WEBHOME"], PIHOLE_WEBSERVER=webserver
        ),
    }
    return {
        name: _render(expression, PIHOLE_WEBSERVER=webserver, domain="stale", **derived)
        for name, expression in FTLCONF.findall(ENV.read_text(encoding="utf-8"))
    }


def _env_file(lines: dict) -> str:
    return "".join(f"{name}={value}\n" for name, value in lines.items())


def _stage() -> list[dict]:
    return load_yaml_any(str(STAGE), default_if_missing=[])


class TestWebserverForm(unittest.TestCase):
    def test_the_computed_domain_is_the_domain_of_the_role(self) -> None:
        services = DataLoader().load_from_file(str(SERVICES), trusted_as_template=True)
        real_get = lookup_loader.get

        def get(name, *args, **kwargs):
            return _Domain() if name == "domain" else real_get(name, *args, **kwargs)

        templar = Templar(loader=DataLoader(), variables={})
        with mock.patch.object(lookup_loader, "get", side_effect=get):
            webserver = templar.template(services["pihole"]["webserver"])
        self.assertEqual(WEBSERVER, webserver)

    def test_the_login_form_manages_the_password_only_without_sso(self) -> None:
        for sso, expected in ((True, {}), (False, {"web_login": ADMIN_VALUE})):
            with self.subTest(sso=sso):
                self.assertEqual(
                    WEBSERVER,
                    values("webserver", _forms(), _application(sso), USERS),
                )
                self.assertEqual(
                    expected, values("login", _forms(), _application(sso), USERS)
                )

    def test_pihole_locks_both_forms_itself(self) -> None:
        forms = _forms()
        self.assertIs(True, forms["webserver"]["native"])
        self.assertIs(True, forms["login"]["native"])
        self.assertEqual([], locks(APPLICATION, forms, _application(False), USERS, {}))

    def test_each_sink_reads_only_its_form(self) -> None:
        variables = load_yaml_any(str(VARS))
        for sink, form in (
            ("PIHOLE_WEBSERVER", "webserver"),
            ("PIHOLE_LOGIN", "login"),
        ):
            with self.subTest(sink=sink):
                self.assertEqual(
                    f"{{{{ lookup('form_values', application_id, '{form}') }}}}",
                    variables[sink],
                )

    def test_the_env_writes_every_managed_value_from_the_sinks(self) -> None:
        for login, password in (({}, ""), ({"web_login": ADMIN_VALUE}, ADMIN_VALUE)):
            with self.subTest(password=bool(password)):
                self.assertEqual(
                    {
                        "FTLCONF_webserver_api_password": f'"{password}"',
                        "FTLCONF_webserver_domain": DOMAIN,
                        "FTLCONF_webserver_paths_webhome": WEBHOME,
                    },
                    _env_lines(WEBSERVER, login),
                )

    def test_the_env_read_names_the_variables_the_env_writes(self) -> None:
        specs = _forms()["webserver"]["fields"]
        self.assertEqual(
            ["FTLCONF_webserver_domain", "FTLCONF_webserver_paths_webhome"],
            dotenv_names(WEBSERVER, specs),
        )

    def test_the_env_read_gives_back_the_sink_and_reports_an_edit(self) -> None:
        specs = _forms()["webserver"]["fields"]
        lines = _env_lines(WEBSERVER, {"web_login": ADMIN_VALUE})
        self.assertEqual(
            WEBSERVER, dotenv_fields(None, _env_file(lines), WEBSERVER, specs)
        )
        edited = {**lines, "FTLCONF_webserver_paths_webhome": "/edited/"}
        self.assertEqual(
            {"domain": DOMAIN, "webhome": "/edited/"},
            dotenv_fields(None, _env_file(edited), WEBSERVER, specs),
        )

    def test_the_stage_reports_the_webserver_form_before_the_backend(self) -> None:
        reports = [task for task in _stage() if ENV_DRIFT in str(task)]
        self.assertEqual(1, len(reports))
        self.assertEqual(
            {
                "forms_env_form": "webserver",
                "forms_env_fields": "{{ PIHOLE_WEBSERVER }}",
            },
            reports[0]["vars"],
        )


if __name__ == "__main__":
    unittest.main()
