from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError

from plugins.lookup.config import LookupModule
from tests.utils.openbao_stub import OpenBaoStub
from utils import openbao_client
from utils.cache import base as cache_base
from utils.cache.reset import _reset_cache_for_tests

APP = "web-app-foo"
TOKEN = "s.deploy-token"
VALUE = "known-secret-value-4711"


def applications(credentials: dict[str, Any]) -> dict[str, Any]:
    return {
        "applications": {
            APP: {
                "secrets": {"credentials": credentials},
                "smtp": {"host": "mail.example.org"},
            }
        }
    }


class TestConfigOpenBao(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        cls.addClassCleanup(_reset_cache_for_tests)
        cls.stub = OpenBaoStub(tokens={TOKEN: ["tenant/ws-a/"]}, logins={})
        cls.stub.put("tenant/ws-a/ssh", {"private_key": VALUE, "public_key": "pub"})
        cls.addClassCleanup(cls.stub.close)

    def setUp(self) -> None:
        cache_base._reset()
        openbao_client._SESSION.clear()
        self.lookup = LookupModule()
        self._cwd = str(Path.cwd())
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)
        self.environ = mock.patch.dict(
            os.environ,
            {
                "BAO_ADDR": self.stub.addr,
                "BAO_TOKEN": TOKEN,
                "BAO_CACERT": self.stub.cafile,
            },
        )
        self.environ.start()

    def tearDown(self) -> None:
        self.environ.stop()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def run_lookup(self, credentials: dict[str, Any], path: str) -> Any:
        return self.lookup.run([APP, path], variables=applications(credentials))[0]

    def test_the_config_lookup_resolves_an_openbao_reference(self) -> None:
        credentials = {"ssh": {"openbao": "tenant/ws-a/ssh#private_key"}}
        self.assertEqual(self.run_lookup(credentials, "secrets.credentials.ssh"), VALUE)

    def test_a_parent_lookup_resolves_the_references_below_it(self) -> None:
        credentials = {
            "ssh": {"openbao": "tenant/ws-a/ssh#private_key"},
            "nested": {"public": {"openbao": "tenant/ws-a/ssh#public_key"}},
            "plain": "x",
        }
        self.assertEqual(
            self.run_lookup(credentials, "secrets.credentials"),
            {"ssh": VALUE, "nested": {"public": "pub"}, "plain": "x"},
        )

    def test_other_values_keep_their_meaning(self) -> None:
        vault = "$ANSIBLE_VAULT;1.1;AES256\n6162"
        credentials = {"plain": "x", "vaulted": vault, "nested": {"key": "k"}}
        before = len(self.stub.requests)
        self.assertEqual(self.run_lookup(credentials, "secrets.credentials.plain"), "x")
        self.assertEqual(
            self.run_lookup(credentials, "secrets.credentials.vaulted"), vault
        )
        self.assertEqual(
            self.run_lookup(credentials, "secrets.credentials.nested"), {"key": "k"}
        )
        self.assertEqual(len(self.stub.requests), before)

    def test_no_reference_outside_the_credentials_is_resolved(self) -> None:
        variables = applications({})
        variables["applications"][APP]["smtp"] = {
            "host": {"openbao": "tenant/ws-a/ssh#private_key"}
        }
        self.assertEqual(
            self.lookup.run([APP, "smtp.host"], variables=variables)[0],
            {"openbao": "tenant/ws-a/ssh#private_key"},
        )

    def test_a_malformed_reference_is_refused(self) -> None:
        for reference in (
            {"openbao": "tenant/ws-a/ssh"},
            {"openbao": "tenant/ws-a/ssh#private_key", "fallback": "x"},
        ):
            with (
                self.subTest(reference=reference),
                self.assertRaises(AnsibleError) as caught,
            ):
                self.run_lookup({"ssh": reference}, "secrets.credentials.ssh")
            self.assertIn(f"{APP}.secrets.credentials.ssh", str(caught.exception))

    def test_a_missing_or_denied_path_fails_with_path_and_field(self) -> None:
        for target in ("tenant/ws-a/gone#key", "tenant/ws-b/ssh#private_key"):
            with self.subTest(target=target), self.assertRaises(AnsibleError) as caught:
                self.run_lookup({"ssh": {"openbao": target}}, "secrets.credentials.ssh")
            message = str(caught.exception)
            path, field = target.split("#")
            self.assertIn(path, message)
            self.assertIn(field, message)
            self.assertNotIn(VALUE, message)

    def test_a_reference_without_a_login_names_the_missing_login(self) -> None:
        with (
            mock.patch.dict(os.environ, {"BAO_TOKEN": ""}),
            self.assertRaises(AnsibleError) as caught,
        ):
            self.run_lookup(
                {"ssh": {"openbao": "tenant/ws-a/ssh#private_key"}},
                "secrets.credentials.ssh",
            )
        self.assertIn("BAO_TOKEN", str(caught.exception))

    def test_a_value_is_fetched_once_per_run(self) -> None:
        credentials = {
            "ssh": {"openbao": "tenant/ws-a/ssh#private_key"},
            "pub": {"openbao": "tenant/ws-a/ssh#public_key"},
        }
        before = len(self.stub.requests)
        self.run_lookup(credentials, "secrets.credentials.ssh")
        self.run_lookup(credentials, "secrets.credentials.pub")
        self.assertEqual(len(self.stub.requests) - before, 1)


if __name__ == "__main__":
    unittest.main()
