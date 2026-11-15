from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.config import LookupModule as ConfigLookup
from plugins.lookup.users import LookupModule as UsersLookup
from plugins.lookup.users import _reset_cache_for_tests
from tests.utils.openbao_stub import OpenBaoStub
from utils import openbao_client
from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import ROLE_FILE_META_USERS

APP = "web-app-foo"
TOKEN = "s.fixture-reader"
VALUE = "known-user-password-4711"
REFERENCE = {"openbao": "platform/fixture/platform/users/alice#password"}


class TestUsersOpenBao(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stub = OpenBaoStub(tokens={TOKEN: ["platform/fixture/"]}, logins={})
        cls.stub.put("platform/fixture/platform/users/alice", {"password": VALUE})
        cls.addClassCleanup(cls.stub.close)

    def setUp(self) -> None:
        openbao_client._SESSION.clear()
        _reset_cache_for_tests()
        self.addCleanup(_reset_cache_for_tests)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        cwd = str(Path.cwd())
        os.chdir(scratch.name)
        self.addCleanup(os.chdir, cwd)
        self.roles = Path(scratch.name) / "roles"
        meta = self.roles / "identity" / ROLE_FILE_META_USERS
        meta.parent.mkdir(parents=True)
        meta.write_text(
            dump_yaml_str(
                {
                    "alice": {"username": "alice", "email": "alice@example.org"},
                    "bob": {"username": "bob", "email": "bob@example.org"},
                }
            ),
            encoding="utf-8",
        )
        environ = mock.patch.dict(
            os.environ,
            {
                "BAO_ADDR": self.stub.addr,
                "BAO_TOKEN": TOKEN,
                "BAO_CACERT": self.stub.cafile,
            },
        )
        environ.start()
        self.addCleanup(environ.stop)

    def users(self, overrides: dict[str, Any], *terms: str) -> Any:
        lookup = UsersLookup()
        lookup._templar = None
        return lookup.run(
            list(terms), variables={"users": overrides}, roles_dir=str(self.roles)
        )[0]

    def config(self, overrides: dict[str, Any], path: str) -> Any:
        lookup = ConfigLookup()
        lookup._templar = None
        variables = {
            "users": overrides,
            "applications": {APP: {"users": {"alice": {}}}},
        }
        return lookup.run([APP, path], variables=variables, roles_dir=str(self.roles))[
            0
        ]

    def test_the_users_lookup_resolves_a_password_reference(self) -> None:
        user = self.users({"alice": {"password": REFERENCE}}, "alice")
        self.assertEqual(user["password"], VALUE)
        self.assertEqual(user["username"], "alice")

    def test_the_full_users_mapping_resolves_every_password_reference(self) -> None:
        users = self.users({"alice": {"password": REFERENCE}, "bob": {"password": "b"}})
        self.assertEqual(users["alice"]["password"], VALUE)
        self.assertEqual(users["bob"]["password"], "b")

    def test_the_config_lookup_resolves_a_user_password_reference(self) -> None:
        overrides = {"alice": {"password": REFERENCE}}
        self.assertEqual(self.config(overrides, "users.alice.password"), VALUE)
        self.assertEqual(self.config(overrides, "users.alice")["password"], VALUE)

    def test_negative_control_a_reference_in_any_other_users_field_is_refused(
        self,
    ) -> None:
        for field, override in (
            ("users.alice.email", {"email": REFERENCE}),
            ("users.alice.tokens.web-app-foo", {"tokens": {APP: REFERENCE}}),
            ("users.alice.authorized_keys.0", {"authorized_keys": [REFERENCE]}),
        ):
            for lookup in (
                lambda o: self.users(o, "alice"),
                self.users,
                lambda o: self.config(o, "users.alice"),
            ):
                with (
                    self.subTest(field=field),
                    self.assertRaises(AnsibleError) as caught,
                ):
                    lookup({"alice": override})
                self.assertIn(field, str(caught.exception))
                self.assertIn("only users.<name>.password", str(caught.exception))

    def test_negative_control_a_value_instead_of_a_reference_reads_no_openbao(
        self,
    ) -> None:
        before = len(self.stub.requests)
        user = self.users({"alice": {"password": "plain-value"}}, "alice")
        self.assertEqual(user["password"], "plain-value")
        self.assertEqual(len(self.stub.requests), before)

    def test_a_missing_field_fails_naming_the_user_password(self) -> None:
        missing = {"openbao": "platform/fixture/platform/users/alice#other"}
        with self.assertRaises(AnsibleError) as caught:
            self.users({"alice": {"password": missing}}, "alice")
        self.assertIn("users.alice.password", str(caught.exception))
        self.assertNotIn(VALUE, str(caught.exception))

    def test_the_carrier_keeps_the_reference(self) -> None:
        lookup = UsersLookup()
        lookup._templar = None
        carried = lookup.run(
            [],
            variables={"users": {"alice": {"password": REFERENCE}}},
            roles_dir=str(self.roles),
            carrier=True,
        )[0]
        self.assertEqual(carried["users"]["alice"]["password"], REFERENCE)


class TestUserReferences(unittest.TestCase):
    def test_only_the_password_leaf_may_hold_a_reference(self) -> None:
        users = {"alice": {"password": REFERENCE, "email": "a@example.org"}}
        self.assertEqual(
            [
                (".".join(parts), str(ref))
                for parts, ref in openbao_client.user_references(users)
            ],
            [("users.alice.password", REFERENCE["openbao"])],
        )

    def test_negative_control_a_whole_user_as_reference_is_refused(self) -> None:
        with self.assertRaises(openbao_client.OpenBaoError) as caught:
            openbao_client.user_references({"alice": REFERENCE})
        self.assertIn("users.alice:", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
