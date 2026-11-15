from __future__ import annotations

import base64
import importlib.util
import json
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-kix"
FORMS = ROLE / ROLE_FILE_META_FORMS
VOLUMES = ROLE / ROLE_FILE_META_VOLUMES
VARS = ROLE / ROLE_FILE_VARS_MAIN
TASKS = ROLE / "tasks" / "00_core.yml"
LOCK_TEMPLATE = ROLE / "templates" / "auth_ldap.conf.j2"
XML_TEMPLATE = ROLE / "templates" / "zzz_auth_ldap.xml.j2"
FILTER = ROLE / "filter_plugins" / "kix_ldap_lock.py"
SINK = "KIX_LDAP_SETTINGS"
DRIFT = "tasks/utils/forms/drift.yml"
ADMINISTRATOR = "Authentication###100-Infinito-LDAP"
USER = "Authentication###200-Infinito-LDAP-User"
KIX_LOCAL_CONFIG_DIR = PurePosixPath("/opt/kix/config")
PROBE_SECRET = "probe'pw\\with$specials"
SETTINGS = {
    "host": "ldap.example",
    "port": 636,
    "base_dn": "ou=users,dc=example",
    "search_user_dn": "cn=administrator,dc=example",
    "uid": "uid",
    "access_attr": "member",
    "administrator_group_dn": "cn=web-app-kix-administrator,ou=roles,dc=example",
    "user_group_dn": "cn=web-app-kix-user,ou=roles,dc=example",
    "contact_sync": {
        "Email": "mail",
        "UserLogin": "uid",
        "PrimaryOrganisationID": "SET:1",
    },
}
GETLOCALCONFIG = (
    "my $Content = do { local $/; <STDIN> };"
    ' my %Hash = eval "($Content)"; die $@ if $@;'
    " print JSON::PP->new->canonical->encode(\\%Hash);"
)


def _filter():
    spec = importlib.util.spec_from_file_location("kix_ldap_lock", FILTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.kix_ldap_lock_fields


def _render(path) -> str:
    variables = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    variables.update(
        {
            SINK: SETTINGS,
            "KIX_LDAP_BIND_PW": PROBE_SECRET,
            "KIX_LDAP_ROLE_SYNC": {},
            "KIX_LDAP_USAGE_CONTEXT_SYNC": {},
            "SOFTWARE_NAME": "Infinito.Nexus",
        }
    )
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(read_text(str(path))))


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _steps() -> list[dict]:
    return [step for task in _tasks() for step in task.get("block", [task])]


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


class TestTheLockedFileCarriesTheSink(unittest.TestCase):
    def test_each_backend_takes_its_managed_fields_from_the_sink(self) -> None:
        held = json.loads(
            base64.b64decode(
                _render(LOCK_TEMPLATE).split("decode_base64('")[1].split("'")[0]
            )
        )
        administrator = held[ADMINISTRATOR][0]["Config"]
        self.assertEqual(SETTINGS["host"], administrator["Host"])
        self.assertEqual(SETTINGS["port"], administrator["Params"]["port"])
        self.assertEqual(SETTINGS["uid"], administrator["AuthAttr"])
        self.assertEqual(SETTINGS["administrator_group_dn"], administrator["GroupDN"])
        self.assertEqual(SETTINGS["user_group_dn"], held[USER][0]["Config"]["GroupDN"])
        self.assertEqual(PROBE_SECRET, administrator["SearchUserPw"])

    def test_both_backends_sync_the_contact_by_the_map_of_the_sink(self) -> None:
        held = json.loads(
            base64.b64decode(
                _render(LOCK_TEMPLATE).split("decode_base64('")[1].split("'")[0]
            )
        )
        for option in (ADMINISTRATOR, USER):
            with self.subTest(option=option):
                (sync,) = held[option][0]["Sync"]
                self.assertEqual(
                    SETTINGS["contact_sync"], sync["Config"]["ContactUserSync"]
                )

    def test_the_spec_checks_the_map_the_form_manages(self) -> None:
        source = load_yaml_any(str(FORMS))["ldap"]["fields"]["contact_sync"]["source"]
        self.assertEqual(
            f"{{{{ lookup('config', application_id, '{source}') }}}}",
            load_yaml_any(str(VARS))["KIX_LDAP_CONTACT_SYNC"],
        )

    def test_the_read_returns_exactly_what_the_write_put_in(self) -> None:
        rendered = _render(LOCK_TEMPLATE).encode("utf-8")
        fields = _filter()({"content": base64.b64encode(rendered).decode("ascii")})
        self.assertEqual(SETTINGS, fields)
        self.assertNotIn(PROBE_SECRET, json.dumps(fields))

    def test_a_missing_or_foreign_file_reports_no_field(self) -> None:
        read = _filter()
        foreign = base64.b64encode(b"('Foo' => 1)").decode("ascii")
        for slurped in ({"failed": True}, {"content": ""}, {"content": foreign}):
            with self.subTest(slurped=slurped):
                self.assertEqual({}, read(slurped))

    @unittest.skipIf(shutil.which("perl") is None, "perl is not installed")
    def test_kix_reads_the_file_as_its_local_config(self) -> None:
        result = subprocess.run(
            ["perl", "-MJSON::PP", "-e", GETLOCALCONFIG],
            input=_render(LOCK_TEMPLATE),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        held = json.loads(result.stdout)
        self.assertEqual({ADMINISTRATOR, USER}, set(held))
        self.assertEqual(PROBE_SECRET, held[ADMINISTRATOR][0]["Config"]["SearchUserPw"])
        self.assertEqual(
            SETTINGS["port"], held[ADMINISTRATOR][0]["Config"]["Params"]["port"]
        )

    def test_the_xml_default_holds_the_same_backends(self) -> None:
        root = ET.fromstring(_render(XML_TEMPLATE))  # noqa: S314 - parses the role's own template rendered from test values, no untrusted input
        locked = json.loads(
            base64.b64decode(
                _render(LOCK_TEMPLATE).split("decode_base64('")[1].split("'")[0]
            )
        )
        for item in root.iter("ConfigItem"):
            with self.subTest(option=item.get("Name")):
                self.assertEqual(
                    locked[item.get("Name")],
                    json.loads(item.find("Setting/Object").text),
                )


class TestTheFormIsLockedByKix(unittest.TestCase):
    def test_the_form_is_native_and_names_every_field_the_read_returns(self) -> None:
        form = load_yaml_any(str(FORMS))["ldap"]
        self.assertIs(True, form["native"])
        self.assertEqual([SINK], form["sinks"])
        self.assertEqual(set(SETTINGS), set(form["fields"]))
        for field, spec in form["fields"].items():
            with self.subTest(field=field):
                self.assertEqual("services.ldap.enabled", spec["when"])

    def test_the_sink_reads_only_its_form(self) -> None:
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'ldap') }}",
            load_yaml_any(str(VARS))[SINK],
        )

    def test_the_file_lands_in_the_local_config_kix_marks_read_only(self) -> None:
        lock = load_yaml_any(str(VOLUMES))["auth_ldap_lock"]
        (mount,) = lock["mounts"]
        self.assertEqual("backend", mount["service"])
        self.assertEqual(KIX_LOCAL_CONFIG_DIR, PurePosixPath(mount["target"]).parent)
        self.assertIn("'auth_ldap.conf'", lock["source"])


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_file_is_read_and_reported_before_it_is_rendered(self) -> None:
        tasks = _steps()
        read = _index(
            tasks,
            lambda task: (
                "KIX_AUTH_LDAP_LOCK_HOST_PATH"
                in str(task.get("ansible.builtin.slurp", {}))
            ),
        )
        report = _index(
            tasks,
            lambda task: DRIFT in str(task.get("ansible.builtin.include_tasks", "")),
        )
        render = _index(
            tasks,
            lambda task: any(
                entry.get("src") == LOCK_TEMPLATE.name
                for entry in task.get("vars", {}).get("role_templates", [])
            ),
        )
        self.assertLess(read, report)
        self.assertLess(report, render)

    def test_the_report_reads_the_fields_of_the_locked_file(self) -> None:
        report = next(
            task
            for task in _steps()
            if DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
        )
        self.assertEqual(
            "{{ kix_ldap_lock_stored | kix_ldap_lock_fields }}",
            report["vars"]["forms_drift_current"]["ldap"],
        )


if __name__ == "__main__":
    unittest.main()
