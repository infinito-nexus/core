from __future__ import annotations

import unittest
import unittest.mock as mock
from typing import Any

from ansible.parsing.dataloader import DataLoader
from ansible.parsing.vault import (
    EncryptedString,
    VaultLib,
    VaultSecret,
    VaultSecretsContext,
)
from ansible.plugins.loader import lookup_loader
from ansible.template import Templar

from plugins.lookup.objstore import LookupModule
from utils.cache.base import _RENDER_GUARD
from utils.cache.reset import _reset_cache_for_tests

PROVIDER = "web-svc-seaweedfs"
FORMS = {
    "web-app-listmonk": "s3",
    "web-app-mattermost": "settings",
    "web-app-odoo": "attachment_storage",
}
SECRET = "objstore-render-secret"
VAULT_CONTEXT = mock.patch.object(VaultSecretsContext, "_current", None)


def setUpModule() -> None:
    VAULT_CONTEXT.start()


def tearDownModule() -> None:
    VAULT_CONTEXT.stop()


def _vaulted(plain: str) -> EncryptedString:
    context = VaultSecretsContext.current(optional=True)
    if context is None:
        context = VaultSecretsContext([("default", VaultSecret(b"objstore-render"))])
        VaultSecretsContext.initialize(context)
    ciphertext = VaultLib(context.secrets).encrypt(plain.encode())
    return EncryptedString(ciphertext=ciphertext.decode())


def _host(*, with_store: bool, vaulted: bool) -> dict[str, Any]:
    group_names = sorted(
        [*FORMS, "svc-db-postgres", *([PROVIDER] if with_store else [])]
    )
    secret_key = _vaulted(SECRET) if vaulted else SECRET
    return {
        "TLS_ENABLED": True,
        "TLS_MODE": "self_signed",
        "DIR_COMPOSITIONS": "/opt/compose/",
        "DEBUG": False,
        "applications": {
            consumer: {"secrets": {"credentials": {"objstore_secret_key": secret_key}}}
            for consumer in FORMS
        },
        "users": {},
        "group_names": group_names,
        "groups": {name: ["localhost"] for name in group_names},
        "DOMAIN_PRIMARY": "infinito.test",
        "SYSTEM_EMAIL_DOMAIN": "infinito.test",
        "ansible_facts": {"os_family": "Debian"},
        "ansible_connection": "local",
        "inventory_hostname": "localhost",
        "RESOURCE_HOST_CPUS_OVERRIDE": 16,
        "RESOURCE_HOST_MEM_MB_OVERRIDE": 64000,
    }


def _resolved(scope: dict[str, Any], *, inside_the_render: bool) -> dict[str, dict]:
    _reset_cache_for_tests()
    loader = DataLoader()
    lookup = LookupModule(loader=loader, templar=Templar(loader=loader))
    _RENDER_GUARD.applications = inside_the_render
    try:
        return {
            consumer: lookup.run([consumer], variables=dict(scope))[0]
            for consumer in FORMS
        }
    finally:
        _RENDER_GUARD.applications = False
        _RENDER_GUARD.nested_payloads = {}


def _form_values(scope: dict[str, Any]) -> dict[str, dict]:
    _reset_cache_for_tests()
    loader = DataLoader()
    templar = Templar(loader=loader, variables=scope)
    form_values = lookup_loader.get("form_values", loader=loader, templar=templar)
    return {
        consumer: form_values.run([consumer, form], variables=dict(scope))[0]
        for consumer, form in FORMS.items()
    }


class TestObjstoreInsideTheApplicationsRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scopes = {
            with_store: _host(with_store=with_store, vaulted=True)
            for with_store in (True, False)
        }
        cls.after = {
            with_store: _resolved(scope, inside_the_render=False)
            for with_store, scope in cls.scopes.items()
        }
        cls.inside = {
            with_store: _resolved(scope, inside_the_render=True)
            for with_store, scope in cls.scopes.items()
        }

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_the_render_resolves_what_the_play_resolves_beside_the_store(
        self,
    ) -> None:
        self.assertEqual(self.after[True], self.inside[True])

    def test_the_render_resolves_what_the_play_resolves_without_the_store(
        self,
    ) -> None:
        self.assertEqual(self.after[False], self.inside[False])

    def test_the_render_reads_the_vaulted_secret_key_as_its_plaintext(self) -> None:
        for consumer, resolved in self.inside[True].items():
            with self.subTest(consumer=consumer):
                self.assertEqual(resolved["secret_key"], SECRET)

    def test_a_host_without_the_store_enables_no_engine_inside_the_render(
        self,
    ) -> None:
        for consumer, resolved in self.inside[False].items():
            with self.subTest(consumer=consumer):
                self.assertFalse(resolved["enabled"])


class TestObjstoreFlagsInsideTheApplicationsRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scope = _host(with_store=False, vaulted=False)
        cls.after = _resolved(scope, inside_the_render=False)
        cls.inside = _resolved(scope, inside_the_render=True)

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_a_group_names_flag_is_no_truthy_string_inside_the_render(self) -> None:
        self.assertEqual(self.after, self.inside)


class TestObjstoreFormSourcesConverge(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scope = _host(with_store=True, vaulted=True)
        cls.play = _resolved(scope, inside_the_render=False)
        cls.values = _form_values(scope)

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_the_mattermost_s3_settings_converge_to_the_object_store(self) -> None:
        store = self.play["web-app-mattermost"]
        settings = self.values["web-app-mattermost"]
        self.assertEqual(
            (
                settings["mm_filesettings_amazons3bucket"],
                settings["mm_filesettings_amazons3endpoint"],
                settings["mm_filesettings_amazons3region"],
            ),
            (store["bucket"], store["endpoint"], store["region"]),
        )

    def test_the_listmonk_s3_form_converges_to_the_object_store(self) -> None:
        store = self.play["web-app-listmonk"]
        s3 = self.values["web-app-listmonk"]
        self.assertEqual(
            (s3["bucket"], s3["url"], s3["public_url"]),
            (store["bucket"], store["url"], store["public_url"]),
        )

    def test_the_odoo_attachment_storage_converges_to_the_object_store(self) -> None:
        self.assertEqual(
            self.values["web-app-odoo"]["directory_path"],
            self.play["web-app-odoo"]["bucket"],
        )


if __name__ == "__main__":
    unittest.main()
