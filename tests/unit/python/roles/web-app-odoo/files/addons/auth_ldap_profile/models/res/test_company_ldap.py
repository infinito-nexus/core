from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from dataclasses import dataclass, replace
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from utils.cache.files import PROJECT_ROOT

MODULE_PATH = (
    PROJECT_ROOT
    / "roles/web-app-odoo/files/addons/auth_ldap_profile/models/res/company_ldap.py"
)
SUPERUSER_ID = 1
NEW_USER_ID = 42
COMPANY_ID = 1
OTHER_COMPANY_ID = 2
CONF = {"company": (COMPANY_ID, "My Company")}
ENTRY = ("uid=biber,ou=users,dc=example,dc=org", {"cn": [b"Harry Beaver"]})
ATTRIBUTES = {
    "ODOO_LDAP_ATTR_FULLNAME": "cn",
    "ODOO_LDAP_ATTR_MAIL": "mail",
    "ODOO_LDAP_ATTR_PHONE": "telephoneNumber",
    "ODOO_LDAP_ATTR_LOCALE": "preferredLanguage",
    "ODOO_LDAP_ATTR_TIMEZONE": "timezone",
    "ODOO_LDAP_ATTR_MEMBER_OF": "memberOf",
}


class Command:
    @staticmethod
    def link(record_id):
        return ("link", record_id)

    @staticmethod
    def set(record_ids):
        return ("set", list(record_ids))


@dataclass(frozen=True)
class Env:
    """Odoo environment double.

    Args:
        uid: the acting user id; None as on Session.authenticate.
        context: the environment context.
        models: model doubles by model name.
        created: (uid, values) of every res.users create, shared across envs.
    """

    uid: int | None
    context: dict
    models: dict
    created: list

    def __getitem__(self, model: str):
        return self.models[model]


class UpstreamCompanyLdap:
    def _with_env(self, env: Env):
        record = type(self)()
        record.env = env
        return record

    def with_user(self, uid: int):
        return self._with_env(replace(self.env, uid=uid))

    def with_context(self, **context):
        return self._with_env(
            replace(self.env, context={**self.env.context, **context})
        )

    def _map_ldap_attributes(self, conf, login, ldap_entry):
        return {
            "name": ldap_entry[1]["cn"][0],
            "login": login,
            "company_id": conf["company"][0],
        }

    def _get_or_create_user(self, conf, login, ldap_entry):
        values = self._map_ldap_attributes(conf, login, ldap_entry)
        self.env.created.append((self.env.uid, values))
        return NEW_USER_ID


def load_model() -> type:
    odoo = ModuleType("odoo")
    odoo.SUPERUSER_ID = SUPERUSER_ID
    odoo.Command = Command
    odoo.models = SimpleNamespace(Model=UpstreamCompanyLdap)
    with patch.dict(sys.modules, {"odoo": odoo}):
        spec = importlib.util.spec_from_file_location("company_ldap", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.ResCompanyLdapProfile


def allowed_companies(values: dict, default: list[int]) -> set[int]:
    """Replay the ``company_ids`` a res.users create ends up with.

    Args:
        values: the create values ``_map_ldap_attributes`` returned.
        default: the ``company_ids`` default, ``env.company.ids``.

    Returns:
        The ids ``_check_user_company`` compares ``company_id`` against.
    """
    if "company_ids" not in values:
        return set(default)
    companies = set()
    for operation, argument in values["company_ids"]:
        if operation == "link":
            companies.add(argument)
        else:
            companies = set(argument)
    return companies


class TestMapLdapAttributes(unittest.TestCase):
    def _map(self, context: dict) -> dict:
        model = load_model()()
        model.env = MagicMock(name="env")
        model.env.context = context
        model.env["infinito.rbac"]._profile.return_value = {"phone": "+49 40 1234567"}
        with patch.dict(os.environ, ATTRIBUTES):
            return model._map_ldap_attributes(CONF, "biber", ENTRY)

    def test_a_sign_in_without_a_user_still_allows_the_ldap_company(self) -> None:
        values = self._map({})

        self.assertEqual(values["company_id"], COMPANY_ID)
        self.assertIn(values["company_id"], allowed_companies(values, default=[]))

    def test_the_allowed_company_follows_the_ldap_configuration_not_the_session(
        self,
    ) -> None:
        values = self._map({})

        self.assertEqual(
            allowed_companies(values, default=[OTHER_COMPANY_ID]), {COMPANY_ID}
        )

    def test_the_role_groups_and_the_profile_reach_the_new_user(self) -> None:
        values = self._map({"infinito_rbac_granted": [7, 9]})

        self.assertEqual(values["group_ids"], [("set", [7, 9])])
        self.assertEqual(values["phone"], "+49 40 1234567")
        self.assertIn(COMPANY_ID, allowed_companies(values, default=[]))


class TestGetOrCreateUser(unittest.TestCase):
    def setUp(self) -> None:
        self.managed = MagicMock(name="managed")
        self.granted = MagicMock(name="granted", ids=[7])
        self.rbac = MagicMock(name="infinito.rbac")
        self.rbac._authorize.return_value = (self.managed, self.granted)
        self.rbac._profile.return_value = {}
        self.model = load_model()()
        self.model.env = Env(
            uid=None,
            context={},
            models={"infinito.rbac": self.rbac, "res.users": MagicMock()},
            created=[],
        )

    def _sign_in(self) -> int:
        with patch.dict(os.environ, ATTRIBUTES):
            return self.model._get_or_create_user(CONF, "biber", ENTRY)

    def test_a_first_sign_in_creates_the_user_as_the_superuser(self) -> None:
        self._sign_in()

        self.assertEqual(
            [uid for uid, _values in self.model.env.created], [SUPERUSER_ID]
        )

    def test_the_created_user_carries_the_role_groups_and_is_synced(self) -> None:
        user_id = self._sign_in()

        ((_uid, values),) = self.model.env.created
        self.assertEqual(user_id, NEW_USER_ID)
        self.assertEqual(values["group_ids"], [("set", [7])])
        self.assertIn(COMPANY_ID, allowed_companies(values, default=[]))
        self.rbac._apply.assert_called_once()
        self.assertEqual(
            self.rbac._apply.call_args.args[1:], (self.managed, self.granted)
        )


if __name__ == "__main__":
    unittest.main()
