from __future__ import annotations

import io
import sys
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))
sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python/workspace"))

import organization
import user as user_m

from ._workspace_fake import (
    CUSTOMER,
    OWNER,
    ROOT,
    STAFF,
    USERS,
    WORKSPACES_CLIENT,
    WS,
    FakeKeycloak,
    state,
)


def erase(kc: FakeKeycloak, user_id: str) -> tuple[int, list[str]]:
    """
    Args:
        kc: the fake Keycloak.
        user_id: USER_ID.

    Returns:
        The exit status and the output lines of ``user erase``.
    """
    env = {"USER_ACTION": "erase", "USER_ID": user_id, "KC_RBAC_GROUP_ROOT": ROOT}
    out = io.StringIO()
    with (
        mock.patch.dict(user_m.os.environ, env, clear=True),
        mock.patch.object(user_m, "service_account", lambda env: kc),
        redirect_stdout(out),
    ):
        status = user_m.main()
    return status, out.getvalue().splitlines()


class TestErase(unittest.TestCase):
    def setUp(self) -> None:
        self.kc = FakeKeycloak(USERS)
        organization.apply(self.kc, WS, WORKSPACES_CLIENT)
        (self.org_id,) = self.kc.orgs
        self.kc.memberships[self.org_id][OWNER] = "UNMANAGED"

    def test_erase_refuses_members_and_staff(self) -> None:
        for user_id, reason in ((OWNER, "member"), (STAFF, "platform_role")):
            with self.subTest(reason=reason):
                before = state(self.kc)
                self.kc.writes.clear()
                status, lines = erase(self.kc, user_id)
                self.assertEqual(status, 3)
                self.assertEqual(
                    lines[-1], f'{{"user":"{user_id}","refused":"{reason}"}}'
                )
                self.assertEqual(self.kc.writes, [])
                self.assertEqual(state(self.kc), before)
                self.assertNotIn(USERS[user_id]["email"], "\n".join(lines))

    def test_a_member_of_an_unmarked_organization_is_erased(self) -> None:
        planted = self.kc.plant_org("hand-made", {})
        self.kc.memberships[planted][CUSTOMER] = "UNMANAGED"
        status, lines = erase(self.kc, CUSTOMER)
        self.assertEqual(
            (status, lines[-1]), (0, f'{{"user":"{CUSTOMER}","erased":true}}')
        )

    def test_erase_deletes_the_account_and_a_rerun_succeeds(self) -> None:
        status, lines = erase(self.kc, CUSTOMER)
        self.assertEqual(status, 0)
        self.assertEqual(
            lines, [f"erased user {CUSTOMER}", f'{{"user":"{CUSTOMER}","erased":true}}']
        )
        self.assertNotIn(CUSTOMER, self.kc.users)
        self.kc.writes.clear()
        status, lines = erase(self.kc, CUSTOMER)
        self.assertEqual(
            (status, lines), (0, [f'{{"user":"{CUSTOMER}","erased":true}}'])
        )
        self.assertEqual(self.kc.writes, [])

    def test_erase_fails_while_the_directory_still_holds_the_account(self) -> None:
        held = self.kc.users[CUSTOMER]

        def reimport(method, path, payload=None, timeout=60):
            result = FakeKeycloak.call(self.kc, method, path, payload, timeout)
            if method == "DELETE" and path == f"users/{CUSTOMER}":
                self.kc.users["reimported"] = {**held, "id": "reimported"}
            return result

        with mock.patch.object(self.kc, "call", reimport):
            status, lines = erase(self.kc, CUSTOMER)
        self.assertEqual(status, 1)
        self.assertFalse([line for line in lines if "erased" in line])

    def test_erase_refuses_a_malformed_user_id_without_a_call(self) -> None:
        self.kc.reads.clear()
        status, lines = erase(self.kc, "not-an-id")
        self.assertEqual((status, lines), (1, []))
        self.assertEqual(self.kc.reads, [])


if __name__ == "__main__":
    unittest.main()
