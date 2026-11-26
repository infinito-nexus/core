from __future__ import annotations

import json
import os
import re
import unittest
import unittest.mock as mock
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles/web-app-shopware"
PLUGIN = "KskHeptacomAdminOpenAuth"
DRIFT = "{{ lookup('path_absolute', 'tasks/utils/forms/drift.yml') }}"
ORIGIN = "http://keycloak:8080"
OIDC = {
    "URL": "https://auth.example.test",
    "CLIENT": {
        "REALM": "main",
        "ID": "shopware",
        "SECRET": "oidc-client-secret",
        "AUTHORIZE_URL": "https://auth.example.test/realms/main/protocol/openid-connect/auth",
    },
}
OLD_CLIENT = {
    "name": "Keycloak",
    "active": True,
    "login": True,
    "connect": True,
    "storeUserToken": True,
    "keepUserUpdated": True,
    "discoveryDocumentUrl": "",
    "authorization_endpoint": "https://auth.example.test/realms/main/protocol/openid-connect/auth",
    "token_endpoint": f"{ORIGIN}/realms/main/protocol/openid-connect/token",
    "userinfo_endpoint": f"{ORIGIN}/realms/main/protocol/openid-connect/userinfo",
    "clientId": "shopware",
}
LOCK = "App\\InfinitoRbac\\StaticSystemConfigLock"


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


def _vars() -> dict:
    return DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )


def _shopware() -> dict:
    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
    )["shopware"]
    stubs = {
        "container_service": lambda _role, _service: "keycloak",
        "config": lambda role, _path: 8080 if role == "web-app-keycloak" else ORIGIN,
    }
    return {
        "admin_auto_redirect": declared["admin_auto_redirect"],
        "oidc_client": _templated(declared["oidc_client"], {"OIDC": OIDC}, stubs),
    }


def _sink(name: str, sso: bool = True, native: bool = False, sso_login: bool = True):
    shopware = _shopware()
    shopware["login"] = {
        "method": {"sso": {"enabled": sso_login}, "native": {"enabled": native}}
    }
    application = {"services": {"sso": {"enabled": sso}, "shopware": shopware}}
    variables = {**_vars(), "application_id": "web-app-shopware"}
    stubs = {"form_values": lambda _app, form: values(form, _forms(), application, {})}
    return dict(_templated(variables[name], variables, stubs))


def _rendered(template: str, settings: dict) -> dict:
    text = read_text(str(ROLE / "templates" / template))
    variables = {
        "SHOPWARE_OIDC_INTERNAL_BASE": ORIGIN,
        "SHOPWARE_OIDC_PLUGIN": _vars()["SHOPWARE_OIDC_PLUGIN"],
        "SHOPWARE_OIDC_PLUGIN_SETTINGS": settings,
    }
    return load_yaml_str(_templated(_trust_as_template(text), variables, {}))


def _static(settings: dict) -> dict:
    return _rendered("static_system_config.yaml.j2", settings)


def _packages(settings: dict) -> dict:
    return _rendered("adminopenauth.yaml.j2", settings)


def _mounts(volume: str) -> list[dict]:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_VOLUMES))[volume]["mounts"]


def _tasks() -> list[dict]:
    return load_yaml_any(str(ROLE / "tasks/setup/oidc.yml"), default_if_missing=[])


def _task(fragment: str) -> dict:
    return next(task for task in _tasks() if fragment in task["name"])


def _position(fragment: str) -> int:
    return next(i for i, task in enumerate(_tasks()) if fragment in task["name"])


def _client_script() -> str:
    return read_text(str(ROLE / "files/php/oidc/client.php"))


class TestPluginConfig(unittest.TestCase):
    def test_the_password_form_is_hidden_while_native_sign_in_is_off(self):
        self.assertEqual(
            {"denyPasswordLogin": True, "enableAutoRedirect": False},
            _sink("SHOPWARE_OIDC_PLUGIN_SETTINGS"),
        )

    def test_the_password_form_stays_while_native_sign_in_is_on(self):
        self.assertEqual(
            {"denyPasswordLogin": False, "enableAutoRedirect": False},
            _sink("SHOPWARE_OIDC_PLUGIN_SETTINGS", native=True),
        )

    def test_nothing_is_managed_while_sso_is_off(self):
        self.assertEqual({}, _sink("SHOPWARE_OIDC_PLUGIN_SETTINGS", sso=False))
        self.assertEqual({}, _sink("SHOPWARE_OIDC_CLIENT_SETTINGS", sso=False))

    def test_the_sink_becomes_static_system_config(self):
        self.assertEqual(
            {
                f"{PLUGIN}.config.denyPasswordLogin": True,
                f"{PLUGIN}.config.enableAutoRedirect": False,
            },
            _static(_sink("SHOPWARE_OIDC_PLUGIN_SETTINGS"))["shopware"][
                "system_config"
            ]["default"],
        )

    def test_an_empty_sink_renders_no_static_system_config(self):
        self.assertEqual({}, _static({}))
        self.assertIn(LOCK, _packages({})["services"])

    def test_negative_control_the_always_loaded_package_config_holds_no_static_keys(
        self,
    ):
        rendered = _packages(_sink("SHOPWARE_OIDC_PLUGIN_SETTINGS"))
        self.assertNotIn("shopware", rendered)
        self.assertIn(LOCK, rendered["services"])

    def test_the_static_file_is_mounted_where_the_package_config_finds_its_plugin(
        self,
    ):
        root = _vars()["SHOPWARE_ROOT"]
        plugin = _vars()["SHOPWARE_OIDC_PLUGIN"]
        self.assertEqual(
            {f"{root}/config/infinito/static_system_config/{plugin}.yaml"},
            {mount["target"] for mount in _mounts("static_system_config")},
        )
        self.assertEqual(
            {f"{root}/config/packages/plugin_static_config.php"},
            {mount["target"] for mount in _mounts("plugin_static_config")},
        )
        deploy = next(
            task
            for task in load_yaml_any(str(ROLE / "tasks/02_manager_ops.yml"))
            if task.get("copy", {}).get("src") == "php/oidc/plugin_static_config.php"
        )
        self.assertEqual(
            "{{ SHOPWARE_PLUGIN_STATIC_CONFIG_HOST }}", deploy["copy"]["dest"]
        )
        for volume in ("static_system_config", "plugin_static_config"):
            with self.subTest(volume=volume):
                self.assertEqual(
                    {"init", "web", "worker", "scheduler"},
                    {mount["service"] for mount in _mounts(volume)},
                )

    def test_no_task_writes_the_plugin_config_beside_the_static_file(self):
        tasks = f"{ROLE / 'tasks'}{os.sep}"
        for path in sorted(iter_project_files(extensions=(".yml",))):
            if not path.startswith(tasks):
                continue
            with self.subTest(path=Path(path).name):
                self.assertNotIn("system:config:set", read_text(path))

    def test_the_form_is_native_and_names_each_static_key(self):
        form = _forms()["plugin_config"]
        self.assertIs(True, form["native"])
        for field, spec in form["fields"].items():
            with self.subTest(field=field):
                self.assertEqual(f'[name="{PLUGIN}.config.{field}"]', spec["selector"])


class TestStaticConfigLock(unittest.TestCase):
    def test_the_lock_listens_to_every_response_with_the_static_config(self):
        service = _packages({})["services"][LOCK]
        self.assertEqual(["%shopware.system_config%"], service["arguments"])
        self.assertEqual(
            [
                {
                    "name": "kernel.event_listener",
                    "event": "kernel.response",
                    "method": "__invoke",
                }
            ],
            service["tags"],
        )

    def test_the_class_the_service_names_is_mounted_where_composer_loads_it(self):
        script = read_text(str(ROLE / "files/php/oidc/static_config_lock.php"))
        self.assertIn("namespace App\\InfinitoRbac;", script)
        self.assertIn("final class StaticSystemConfigLock", script)
        volume = load_yaml_any(str(ROLE / ROLE_FILE_META_VOLUMES))["static_config_lock"]
        host = _vars()["SHOPWARE_STATIC_CONFIG_LOCK_HOST"]
        self.assertTrue(host.endswith("'StaticSystemConfigLock.php' ] | path_join }}"))
        self.assertIn("'StaticSystemConfigLock.php'", volume["source"])
        self.assertEqual(
            {"init", "web", "worker", "scheduler"},
            {mount["service"] for mount in volume["mounts"]},
        )
        self.assertEqual(
            {"/var/www/html/src/InfinitoRbac/StaticSystemConfigLock.php"},
            {mount["target"] for mount in volume["mounts"]},
        )
        deploy = next(
            task
            for task in load_yaml_any(str(ROLE / "tasks/02_manager_ops.yml"))
            if task.get("copy", {}).get("src") == "php/oidc/static_config_lock.php"
        )
        self.assertEqual(
            "{{ SHOPWARE_STATIC_CONFIG_LOCK_HOST }}", deploy["copy"]["dest"]
        )


class TestClient(unittest.TestCase):
    def test_the_client_sink_equals_the_old_payload(self):
        self.assertEqual(OLD_CLIENT, _sink("SHOPWARE_OIDC_CLIENT_SETTINGS"))

    def test_the_internal_origin_keeps_the_container_hop(self):
        self.assertEqual(ORIGIN, _shopware()["oidc_client"]["internal_origin"])

    def test_the_login_flag_follows_the_sso_login_method(self):
        self.assertIs(
            False, _sink("SHOPWARE_OIDC_CLIENT_SETTINGS", sso_login=False)["login"]
        )

    def test_the_client_secret_stays_out_of_the_form_and_the_sink(self):
        self.assertNotIn("clientSecret", _forms()["client"]["fields"])
        self.assertNotIn(
            OIDC["CLIENT"]["SECRET"], json.dumps(_sink("SHOPWARE_OIDC_CLIENT_SETTINGS"))
        )

    def test_the_form_waits_for_an_upstream_lock(self):
        form = _forms()["client"]
        self.assertEqual("pending", form["lock"])
        self.assertTrue(form["issue"].strip())
        self.assertNotIn("native", form)

    def test_the_script_nests_exactly_the_provider_fields_in_config(self):
        listed = re.search(r"const CONFIG_FIELDS = \[([^\]]*)\];", _client_script())
        self.assertEqual(
            {
                field
                for field, spec in _forms()["client"]["fields"].items()
                if spec["selector"].startswith('[name="config.')
            },
            set(re.findall(r"'([^']+)'", listed[1])),
        )


class TestClientConverge(unittest.TestCase):
    def test_the_drift_report_runs_between_the_read_and_the_write(self):
        self.assertLess(_position("Read the stored"), _position("Report the managed"))
        self.assertLess(
            _position("Report the managed"), _position("Ensure the Keycloak login")
        )

    def test_the_read_never_receives_the_client_secret(self):
        read = _task("Read the stored")["ansible.builtin.shell"]
        write = _task("Ensure the Keycloak login")["ansible.builtin.shell"]
        self.assertNotIn("OIDC_CLIENT_SECRET", read["cmd"])
        self.assertEqual(
            "{{ lookup('ansible.builtin.file', role_path ~ '/files/php/dal.php') }}\n"
            "{{ lookup('ansible.builtin.file', role_path ~ '/files/php/oidc/client.php') }}",
            read["stdin"],
        )
        self.assertIn("OIDC.CLIENT.SECRET", write["stdin"])
        self.assertIn("-e OIDC_CLIENT_MODE=read", read["cmd"])
        self.assertIn("--user {{ SHOPWARE_USER }}", read["cmd"])

    def test_the_read_and_the_write_hand_the_script_the_same_settings(self):
        settings = "-e OIDC_CLIENT_SETTINGS={{ SHOPWARE_OIDC_CLIENT_SETTINGS | to_json | quote }}"
        read = _task("Read the stored")
        write = _task("Ensure the Keycloak login")
        self.assertIn(settings, read["ansible.builtin.shell"]["cmd"])
        self.assertIn(settings, write["ansible.builtin.shell"]["cmd"])
        self.assertIs(False, read["changed_when"])
        self.assertEqual(read["no_log"], write["no_log"])

    def test_the_drift_report_names_the_form(self):
        task = _task("Report the managed")
        self.assertEqual(DRIFT, task["include_tasks"])
        node = task["vars"]["forms_drift_current"]["client"]
        report = json.dumps({"settings": {"login": False}})
        stored = {"shopware_oidc_client_stored": {"stdout_lines": ["Notice", report]}}
        self.assertEqual(
            {"login": False}, _templated(_trust_as_template(node), stored, {})
        )


if __name__ == "__main__":
    unittest.main()
