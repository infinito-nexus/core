from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import dump_yaml_str, load_yaml_str

from . import PROJECT_ROOT

PLUGIN = (
    PROJECT_ROOT
    / "roles"
    / "web-app-semaphore"
    / "filter_plugins"
    / "semaphore_fixture_platform.py"
)
HOST = "platform"
TARGET = "target"
CONNECTION = {"ansible_host": "host.docker.internal", "ansible_connection": "ssh"}
LIVE = "LiveValue-must-not-leave"
VAULT = '!vault "$ANSIBLE_VAULT;1.1;AES256\\n3132"'
ADMIN_REF = {
    "openbao": "platform/fixture/platform/users/platform_administrator#password"
}
KNOT_REF = {
    "openbao": "platform/fixture/platform/apps/svc-dns-knot#transfer_tsig_secret"
}
REFERENCES = {
    "users": {"platform_administrator": {"password": ADMIN_REF}},
    "applications": {
        "svc-dns-knot": {"secrets": {"credentials": {"transfer_tsig_secret": KNOT_REF}}}
    },
}


def _load():
    spec = importlib.util.spec_from_file_location("semaphore_fixture_platform", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


platform = _load()

PLATFORM_INVENTORY = dump_yaml_str(
    {
        "all": {
            "children": {
                "web-app-keycloak": {"hosts": {"localhost": {}}},
                "web-app-semaphore": {"hosts": {"localhost": {}}},
                "web-svc-html": {"hosts": {"other": {}}},
            }
        }
    }
)

PLATFORM_HOST_VARS = f"""
ansible_connection: local
ansible_become_password: {VAULT}
DOMAIN_PRIMARY: infinito.example
RUNTIME: dev
users:
  platform_administrator:
    username: administrator
    email: administrator@infinito.example
    password: {VAULT}
  biber:
    username: biber
    password: {LIVE}
applications:
  svc-dns-knot:
    secrets:
      credentials:
        transfer_tsig_secret: {VAULT}
  web-app-keycloak:
    services:
      keycloak:
        organizations:
          enabled: true
    secrets:
      credentials:
        administrator_password: {VAULT}
        nested:
          token: {LIVE}
"""


def built(text=PLATFORM_HOST_VARS, references=REFERENCES):
    return load_yaml_str(
        platform.semaphore_fixture_host_vars(text, references, CONNECTION)
    )


def devices(*hosts):
    return dump_yaml_str(
        {"all": {"children": {"web-svc-html": {"hosts": {h: {} for h in hosts}}}}}
    )


class TestHostVars(unittest.TestCase):
    def test_the_credentials_are_the_references_alone(self):
        host_vars = built()
        self.assertEqual(
            host_vars["users"]["platform_administrator"]["password"], ADMIN_REF
        )
        self.assertNotIn("password", host_vars["users"]["biber"])
        self.assertEqual(
            host_vars["applications"]["svc-dns-knot"]["secrets"],
            {"credentials": {"transfer_tsig_secret": KNOT_REF}},
        )
        self.assertNotIn("secrets", host_vars["applications"]["web-app-keycloak"])

    def test_no_credential_value_and_no_ciphertext_survive(self):
        text = platform.semaphore_fixture_host_vars(
            PLATFORM_HOST_VARS, REFERENCES, CONNECTION
        )
        for leaked in (LIVE, "ANSIBLE_VAULT", "3132"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, text)

    def test_the_platform_settings_are_kept_and_the_connection_replaced(self):
        host_vars = built()
        self.assertEqual(host_vars["DOMAIN_PRIMARY"], "infinito.example")
        self.assertEqual(
            host_vars["users"]["platform_administrator"]["email"],
            "administrator@infinito.example",
        )
        self.assertTrue(
            host_vars["applications"]["web-app-keycloak"]["services"]["keycloak"][
                "organizations"
            ]["enabled"]
        )
        self.assertEqual(
            {k: v for k, v in host_vars.items() if k.startswith("ansible_")}, CONNECTION
        )

    def test_negative_control_a_vaulted_value_outside_the_credentials_is_refused(self):
        for planted in (
            f"MAILER_TOKEN: {VAULT}\n",
            f"applications:\n  web-app-semaphore:\n    api_token: {VAULT}\n",
            f"users:\n  biber:\n    totp: {VAULT}\n",
        ):
            with (
                self.subTest(planted=planted.splitlines()[0]),
                self.assertRaises(AnsibleFilterError),
            ):
                platform.semaphore_fixture_host_vars(planted, REFERENCES, CONNECTION)

    def test_negative_control_secrets_beside_the_credentials_are_refused(self):
        planted = "applications:\n  web-app-keycloak:\n    secrets:\n      tokens:\n        api: x\n"
        with self.assertRaises(AnsibleFilterError):
            platform.semaphore_fixture_host_vars(planted, REFERENCES, CONNECTION)

    def test_negative_control_a_credential_value_in_the_references_is_refused(self):
        for planted in (
            {"users": {"biber": {"password": LIVE}}},
            {
                "applications": {
                    "svc-dns-knot": {
                        "secrets": {"credentials": {"transfer_tsig_secret": LIVE}}
                    }
                }
            },
        ):
            with self.subTest(planted=planted), self.assertRaises(AnsibleFilterError):
                platform.semaphore_fixture_host_vars(
                    PLATFORM_HOST_VARS, planted, CONNECTION
                )


class TestWorkspacesInventory(unittest.TestCase):
    def test_the_platform_host_joins_every_group_of_the_platform_inventory(self):
        self.assertEqual(
            load_yaml_str(
                platform.semaphore_fixture_workspaces(
                    PLATFORM_INVENTORY, "localhost", HOST
                )
            ),
            {
                "all": {
                    "children": {
                        "web-app-keycloak": {"hosts": {HOST: {}}},
                        "web-app-semaphore": {"hosts": {HOST: {}}},
                    }
                }
            },
        )

    def test_a_platform_host_in_no_group_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            platform.semaphore_fixture_workspaces(PLATFORM_INVENTORY, "absent", HOST)


class TestInventoryFindings(unittest.TestCase):
    def setUp(self):
        self.workspaces = platform.semaphore_fixture_workspaces(
            PLATFORM_INVENTORY, "localhost", HOST
        )

    def test_the_two_inventories_keep_their_hosts_apart(self):
        self.assertEqual(
            platform.semaphore_fixture_inventory_findings(
                devices(TARGET), self.workspaces, HOST, TARGET
            ),
            [],
        )

    def test_negative_control_a_platform_host_planted_in_devices_fails(self):
        self.assertEqual(
            platform.semaphore_fixture_inventory_findings(
                devices(TARGET, HOST), self.workspaces, HOST, TARGET
            ),
            [
                f"devices.yml lists the platform host {HOST}, so every deploy would reach it"
            ],
        )

    def test_negative_control_a_target_planted_in_workspaces_fails(self):
        workspaces = dump_yaml_str(
            {
                "all": {
                    "children": {
                        "web-app-semaphore": {"hosts": {HOST: {}}},
                        "web-svc-html": {"hosts": {TARGET: {}}},
                    }
                }
            }
        )
        self.assertEqual(
            platform.semaphore_fixture_inventory_findings(
                devices(TARGET), workspaces, HOST, TARGET
            ),
            [
                f"workspaces.yml lists ['{HOST}', '{TARGET}'], not the platform host {HOST} alone"
            ],
        )


FIXTURE_KEY = "ssh-ed25519 AAAAfixture fixture"
OTHER_KEYS = {
    "app-control": "ssh-ed25519 AAAAcontrol",
    "deploy": "ssh-ed25519 AAAAdeploy",
    "target": "ssh-ed25519 AAAAtarget",
}


class TestKeyFindings(unittest.TestCase):
    def test_a_distinct_fixture_key_has_no_finding(self):
        self.assertEqual(
            platform.semaphore_fixture_key_findings(FIXTURE_KEY, OTHER_KEYS), []
        )

    def test_negative_control_a_key_equal_to_app_control_deploy_or_target_is_caught(
        self,
    ):
        for name in OTHER_KEYS:
            with self.subTest(name=name):
                others = {**OTHER_KEYS, name: "ssh-ed25519 AAAAfixture other-comment"}
                self.assertEqual(
                    platform.semaphore_fixture_key_findings(FIXTURE_KEY, others),
                    [f"the fixture key equals the {name} key"],
                )


if __name__ == "__main__":
    unittest.main()
