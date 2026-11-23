from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from utils.cache.files import PROJECT_ROOT

MODULE_PATH = (
    PROJECT_ROOT
    / "roles/web-app-odoo/files/addons/auth_ldap_profile/models/res/company_ldap.py"
)
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
}


class Command:
    @staticmethod
    def link(record_id):
        return ("link", record_id)

    @staticmethod
    def set(record_ids):
        return ("set", list(record_ids))


class UpstreamCompanyLdap:
    def _map_ldap_attributes(self, conf, login, ldap_entry):
        return {
            "name": ldap_entry[1]["cn"][0],
            "login": login,
            "company_id": conf["company"][0],
        }


def load_model() -> type:
    odoo = ModuleType("odoo")
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


if __name__ == "__main__":
    unittest.main()
