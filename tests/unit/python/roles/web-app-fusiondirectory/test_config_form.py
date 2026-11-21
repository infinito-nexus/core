from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.applications.forms import locks
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

APPLICATION = "web-app-fusiondirectory"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
LDAP_TASKS = ROLE / "tasks" / "01_ldap.yml"
BOOTSTRAP = ROLE / "files" / "shell" / "ldap" / "bootstrap.sh"
READ_CONFIG = ROLE / "files" / "shell" / "ldap" / "read_config.sh"
LOADER = ROLE / "templates" / "javascript.js.j2"
SHARED_RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
DRIFT_TASKS = "tasks/utils/forms/drift.yml"
CONFIG = {
    "login_method": "LoginHTTPHeader",
    "http_header": "X_FORWARDED_PREFERRED_USERNAME",
    "theme": "breezy",
    "timezone": "Europe/Berlin",
    "user_rdn": "ou=people",
    "group_rdn": "ou=groups",
}
SINK = {
    "fdLoginMethod": "LoginHTTPHeader",
    "fdHttpHeaderAuthHeaderName": "X_FORWARDED_PREFERRED_USERNAME",
    "fdTheme": "breezy",
    "fdTimezone": "Europe/Berlin",
    "fdUserRDN": "ou=people",
    "fdGroupRDN": "ou=groups",
    "fdOGroupRDN": "ou=groups",
}
ENFORCED = ("fdLoginMethod", "fdHttpHeaderAuthHeaderName")


class _Config(LookupBase):
    def __init__(self, sso: bool, flavor: str) -> None:
        super().__init__()
        self._held = {"services.sso.enabled": sso, "services.sso.flavor": flavor}

    def run(self, terms, variables=None, **kwargs):
        application, path = terms
        if application != APPLICATION:
            raise AssertionError(f"read {application}, not {APPLICATION}")
        return [self._held[path]]


def _forms() -> dict:
    return load_yaml_any(str(FORMS), default_if_missing={})


def _render(expression, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _login_method(sso: bool, flavor: str) -> str:
    services = DataLoader().load_from_file(str(SERVICES), trusted_as_template=True)
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "config":
            return _Config(sso, flavor)
        return real_get(name, *args, **kwargs)

    templar = Templar(loader=DataLoader(), variables={})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(services["fusiondirectory"]["config"]["login_method"])


def _ldap_tasks() -> list[dict]:
    return load_yaml_any(str(LDAP_TASKS), default_if_missing=[])


def _task(fragment: str) -> int:
    return next(
        index
        for index, task in enumerate(_ldap_tasks())
        if fragment in str(task.get("ansible.builtin.include_tasks"))
        or fragment in str(task.get("ansible.builtin.shell", {}).get("stdin"))
    )


def _read_config(ldapsearch: str, attributes: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "ldapsearch"
        stub.write_text(f"#!/usr/bin/env bash\n{ldapsearch}\n", encoding="utf-8")
        stub.chmod(0o755)
        env = {
            "PATH": f"{tmp}:{os.environ['PATH']}",
            "FD_READ_ATTRIBUTES": attributes,
            "LDAP01_HOST": "ldap",
            "LDAP01_PORT": "389",
            "LDAP01_BASE_DN": "dc=example,dc=test",
            "LDAP01_ADMIN_DN": "cn=admin,dc=example,dc=test",
            "LDAP01_ADMIN_PASS": "bind-value-0",
        }
        return subprocess.run(
            ["bash", str(READ_CONFIG)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )


class TestConfigForm(unittest.TestCase):
    def test_the_login_method_follows_the_oauth2_gate(self) -> None:
        for sso, flavor, expected in (
            (True, "oauth2", "LoginHTTPHeader"),
            (False, "oauth2", "LoginPost"),
            (True, "oidc", "LoginPost"),
        ):
            with self.subTest(sso=sso, flavor=flavor):
                self.assertEqual(expected, _login_method(sso, flavor))

    def test_the_form_carries_every_managed_setting(self) -> None:
        application = {"services": {"fusiondirectory": {"config": CONFIG}}}
        self.assertEqual(SINK, values("config", _forms(), application, {}))
        self.assertEqual(
            {field: SINK[field] for field in ENFORCED},
            values("config", _forms(), application, {}, "enforced"),
        )

    def test_the_renderer_locks_only_the_enforced_settings(self) -> None:
        application = {"services": {"fusiondirectory": {"config": CONFIG}}}
        found = locks(APPLICATION, _forms(), application, {}, {})
        self.assertEqual(
            [
                ("/main.php", "#fdLoginMethod"),
                ("/main.php", "#fdHttpHeaderAuthHeaderName"),
            ],
            [(lock["page"], lock["selector"]) for lock in found],
        )
        services = load_yaml_any(str(SERVICES))
        self.assertIs(True, services["javascript"]["enabled"])
        self.assertIn(SHARED_RENDERER, read_text(str(LOADER)))

    def test_the_sink_reads_only_the_config_form(self) -> None:
        variables = load_yaml_any(str(VARS))
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'config') }}",
            variables["FUSIONDIRECTORY_CONFIG"],
        )

    def test_the_bootstrap_takes_every_managed_setting_from_the_sink(self) -> None:
        bootstrap = _ldap_tasks()[_task("bootstrap.sh")]
        variables = load_yaml_any(str(VARS))
        header = _render(
            variables["FUSIONDIRECTORY_HTTP_HEADER_NAME"], FUSIONDIRECTORY_CONFIG=SINK
        )
        rendered = {
            name: _render(
                bootstrap["environment"][name],
                FUSIONDIRECTORY_CONFIG=SINK,
                FUSIONDIRECTORY_HTTP_HEADER_NAME=header,
            )
            for name in (
                "FD_GROUP_RDN",
                "FD_HTTP_HEADER_NAME",
                "FD_LOGIN_METHOD",
                "FD_OGROUP_RDN",
                "FD_THEME",
                "FD_TIMEZONE",
                "FD_USER_RDN",
            )
        }
        self.assertEqual(
            {
                "FD_GROUP_RDN": "ou=groups",
                "FD_HTTP_HEADER_NAME": "X_FORWARDED_PREFERRED_USERNAME",
                "FD_LOGIN_METHOD": "LoginHTTPHeader",
                "FD_OGROUP_RDN": "ou=groups",
                "FD_THEME": "breezy",
                "FD_TIMEZONE": "Europe/Berlin",
                "FD_USER_RDN": "ou=people",
            },
            rendered,
        )
        script = read_text(str(BOOTSTRAP))
        for line in (
            "fdTheme: ${FD_THEME}",
            "fdOGroupRDN: ${FD_OGROUP_RDN}",
            'reconcile "$config_dn" fdLoginMethod "$FD_LOGIN_METHOD"',
        ):
            with self.subTest(line=line):
                self.assertIn(line, script)

    def test_the_drift_report_runs_after_the_read_and_before_the_bootstrap(
        self,
    ) -> None:
        read = _task("read_config.sh")
        report = _task(DRIFT_TASKS)
        self.assertLess(read, report)
        self.assertLess(report, _task("bootstrap.sh"))
        task = _ldap_tasks()[read]
        self.assertEqual("fusiondirectory_config_held", task["register"])
        self.assertIs(False, task["changed_when"])
        self.assertIn(
            "lookup('form_values', application_id, 'config', mode='enforced')",
            task["environment"]["FD_READ_ATTRIBUTES"],
        )
        current = _ldap_tasks()[report]["vars"]["forms_drift_current"]
        for stdout, expected in (
            (
                (
                    "fdLoginMethod: LoginPost\n"
                    "fdHttpHeaderAuthHeaderName: X_FORWARDED_PREFERRED_USERNAME\n"
                ),
                {
                    "fdLoginMethod": "LoginPost",
                    "fdHttpHeaderAuthHeaderName": "X_FORWARDED_PREFERRED_USERNAME",
                },
            ),
            ("", {}),
        ):
            with self.subTest(stdout=stdout):
                self.assertEqual(["config"], list(current))
                self.assertEqual(
                    expected,
                    _render(
                        current["config"],
                        fusiondirectory_config_held={"stdout": stdout},
                    ),
                )

    def test_the_read_prints_only_the_requested_attributes(self) -> None:
        ldif = (
            "printf 'dn: cn=config\\nfdLoginMethod: LoginPost\\n"
            "fdTheme: breezy\\nfdHttpHeaderAuthHeaderName: X_REMOTE\\n'"
        )
        result = _read_config(ldif, " ".join(ENFORCED))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "fdLoginMethod: LoginPost\nfdHttpHeaderAuthHeaderName: X_REMOTE\n",
            result.stdout,
        )

    def test_the_read_holds_nothing_before_the_bootstrap(self) -> None:
        result = _read_config("exit 32", " ".join(ENFORCED))
        self.assertEqual((0, ""), (result.returncode, result.stdout))

    def test_the_read_fails_on_any_other_ldap_error(self) -> None:
        result = _read_config("exit 49", " ".join(ENFORCED))
        self.assertEqual(49, result.returncode)

    def test_the_read_fails_when_the_attribute_match_itself_fails(self) -> None:
        result = _read_config("printf 'fdTheme: breezy\\n'", "fdTheme[")
        self.assertEqual(2, result.returncode, result.stderr)

    def test_the_bind_password_never_reaches_the_arguments(self) -> None:
        result = _read_config('printf "fdLoginMethod: %s\\n" "$*"', " ".join(ENFORCED))
        self.assertNotIn("bind-value-0", result.stdout)
        self.assertIn("-y", result.stdout.split())


if __name__ == "__main__":
    unittest.main()
