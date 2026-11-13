from __future__ import annotations

import re
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

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
DOMAIN = "pihole.example.test"
WEBHOME = "/admin/"
ADMIN_VALUE = "admin-value-0"
USERS = {"platform_administrator": {"password": ADMIN_VALUE}}
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
            "pihole": {"webserver": {"domain": DOMAIN, "webhome": WEBHOME}},
        }
    }


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _env_lines(**variables) -> dict:
    return {
        name: _render(expression, **variables)
        for name, expression in FTLCONF.findall(ENV.read_text(encoding="utf-8"))
    }


class TestWebserverForm(unittest.TestCase):
    def test_the_computed_domain_is_the_domain_of_the_role(self) -> None:
        services = DataLoader().load_from_file(str(SERVICES), trusted_as_template=True)
        real_get = lookup_loader.get

        def get(name, *args, **kwargs):
            return _Domain() if name == "domain" else real_get(name, *args, **kwargs)

        templar = Templar(loader=DataLoader(), variables={})
        with mock.patch.object(lookup_loader, "get", side_effect=get):
            webserver = templar.template(services["pihole"]["webserver"])
        self.assertEqual({"domain": DOMAIN, "webhome": WEBHOME}, webserver)

    def test_the_form_manages_the_password_only_without_sso(self) -> None:
        shared = {"domain": DOMAIN, "webhome": WEBHOME}
        for sso, expected in (
            (True, shared),
            (False, {**shared, "web_login": ADMIN_VALUE}),
        ):
            with self.subTest(sso=sso):
                self.assertEqual(
                    expected, values("webserver", _forms(), _application(sso), USERS)
                )

    def test_pihole_locks_the_form_itself(self) -> None:
        forms = _forms()
        self.assertIs(True, forms["webserver"]["native"])
        self.assertEqual([], locks(APPLICATION, forms, _application(False), USERS, {}))

    def test_the_sink_reads_only_the_webserver_form(self) -> None:
        variables = load_yaml_any(str(VARS))
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'webserver') }}",
            variables["PIHOLE_WEBSERVER"],
        )

    def test_the_env_writes_every_managed_value_from_the_sink(self) -> None:
        variables = load_yaml_any(str(VARS))
        for sink, password in (
            ({"domain": DOMAIN, "webhome": WEBHOME}, ""),
            (
                {"domain": DOMAIN, "webhome": WEBHOME, "web_login": ADMIN_VALUE},
                ADMIN_VALUE,
            ),
        ):
            with self.subTest(password=bool(password)):
                derived = {
                    name: _render(variables[name], PIHOLE_WEBSERVER=sink)
                    for name in ("PIHOLE_PASSWORD", "PIHOLE_WEBHOME")
                }
                self.assertEqual(
                    {
                        "FTLCONF_webserver_api_password": f'"{password}"',
                        "FTLCONF_webserver_domain": DOMAIN,
                        "FTLCONF_webserver_paths_webhome": WEBHOME,
                    },
                    _env_lines(PIHOLE_WEBSERVER=sink, domain="stale", **derived),
                )


if __name__ == "__main__":
    unittest.main()
