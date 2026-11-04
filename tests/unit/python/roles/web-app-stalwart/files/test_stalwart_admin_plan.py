from __future__ import annotations

import importlib.util
import unittest

from . import PROJECT_ROOT

DOMAIN = "d1"
ADMIN_ROLE = "r-admin"
USER_ROLE = "r-user"


def _load():
    path = PROJECT_ROOT / "roles/web-app-stalwart/files/python/stalwart_admin_plan.py"
    spec = importlib.util.spec_from_file_location("stalwart_admin_plan", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _account(account_id, name, roles=None, kind="User", domain=DOMAIN):
    account = {"id": account_id, "name": name, "@type": kind, "domainId": domain}
    if roles is not None:
        account["roles"] = {
            "@type": "Custom",
            "roleIds": dict.fromkeys(roles, True),
        }
    return account


class TestStalwartAdminPlan(unittest.TestCase):
    def setUp(self):
        self.plan = _load().stalwart_admin_plan

    def test_named_administrator_account_is_granted(self):
        result = self.plan([_account("a1", "alice")], DOMAIN, ["alice"], ADMIN_ROLE)
        self.assertEqual(result, {"grant_ids": ["a1"], "revoke_ids": []})

    def test_named_administrator_already_holding_the_role_is_granted_again(self):
        result = self.plan(
            [_account("a1", "alice", roles=[ADMIN_ROLE, USER_ROLE])],
            DOMAIN,
            ["alice"],
            ADMIN_ROLE,
        )
        self.assertEqual(result["grant_ids"], ["a1"])

    def test_other_account_holding_the_admin_role_is_revoked(self):
        result = self.plan(
            [_account("m1", "mallory", roles=[ADMIN_ROLE, USER_ROLE])],
            DOMAIN,
            ["alice"],
            ADMIN_ROLE,
        )
        self.assertEqual(result, {"grant_ids": [], "revoke_ids": ["m1"]})

    def test_other_account_with_user_role_only_is_left_alone(self):
        result = self.plan(
            [_account("b1", "biber", roles=[USER_ROLE])], DOMAIN, ["alice"], ADMIN_ROLE
        )
        self.assertEqual(result, {"grant_ids": [], "revoke_ids": []})

    def test_account_without_roles_is_not_revoked(self):
        result = self.plan([_account("b1", "biber")], DOMAIN, ["alice"], ADMIN_ROLE)
        self.assertEqual(result["revoke_ids"], [])

    def test_account_whose_roles_carry_no_role_ids_is_not_revoked(self):
        account = _account("b1", "biber")
        account["roles"] = {"@type": "User"}
        result = self.plan([account], DOMAIN, ["alice"], ADMIN_ROLE)
        self.assertEqual(result["revoke_ids"], [])

    def test_account_of_another_domain_is_ignored(self):
        result = self.plan(
            [
                _account("a2", "alice", domain="d2"),
                _account("m2", "mallory", roles=[ADMIN_ROLE], domain="d2"),
            ],
            DOMAIN,
            ["alice"],
            ADMIN_ROLE,
        )
        self.assertEqual(result, {"grant_ids": [], "revoke_ids": []})

    def test_group_principal_is_ignored(self):
        result = self.plan(
            [
                _account("g1", "alice", kind="Group"),
                _account("g2", "staff", roles=[ADMIN_ROLE], kind="Group"),
            ],
            DOMAIN,
            ["alice"],
            ADMIN_ROLE,
        )
        self.assertEqual(result, {"grant_ids": [], "revoke_ids": []})


if __name__ == "__main__":
    unittest.main()
