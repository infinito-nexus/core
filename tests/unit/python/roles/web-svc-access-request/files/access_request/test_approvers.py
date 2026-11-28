from __future__ import annotations

import importlib
import sys
import unittest

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-access-request" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

approvers = importlib.import_module("access_request.approvers")
store = importlib.import_module("access_request.store")

PLATFORM = "/roles/web-svc-access-request/administrator"
APP_ADMIN = "/roles/web-app-blog/administrator"
ROLES = [
    {
        "id": "editor",
        "role": "editor",
        "tenant": "",
        "path": "/roles/web-app-blog/editor",
        "administrator": False,
    },
    {
        "id": "administrator",
        "role": "administrator",
        "tenant": "",
        "path": APP_ADMIN,
        "administrator": True,
    },
    {
        "id": "a.example/administrator",
        "role": "administrator",
        "tenant": "a.example",
        "path": "/roles/web-app-blog/a.example/administrator",
        "administrator": True,
    },
]
REQUESTED = ["editor", "administrator"]


def _person(*groups: str):
    return store.Person("sub", "approver", "approver@example.org", groups)


class TestGrantable(unittest.TestCase):
    def test_a_platform_administrator_may_grant_every_requested_role(self):
        self.assertEqual(
            REQUESTED,
            approvers.grantable(_person(PLATFORM), ROLES, REQUESTED, PLATFORM),
        )

    def test_an_application_administrator_may_grant_only_the_roles_below_it(self):
        self.assertEqual(
            ["editor"],
            approvers.grantable(_person(APP_ADMIN), ROLES, REQUESTED, PLATFORM),
        )

    def test_a_tenant_administrator_grants_nothing(self):
        self.assertEqual(
            [],
            approvers.grantable(
                _person("/roles/web-app-blog/a.example/administrator"),
                ROLES,
                REQUESTED,
                PLATFORM,
            ),
        )

    def test_a_user_without_an_administrator_group_grants_nothing(self):
        self.assertEqual(
            [],
            approvers.grantable(
                _person("/roles/web-app-blog/editor"), ROLES, REQUESTED, PLATFORM
            ),
        )

    def test_a_role_the_request_does_not_name_is_never_offered(self):
        self.assertEqual(
            ["editor"],
            approvers.grantable(_person(PLATFORM), ROLES, ["editor"], PLATFORM),
        )


if __name__ == "__main__":
    unittest.main()
