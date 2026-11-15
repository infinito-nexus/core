from __future__ import annotations

import copy
import io
import json
import sys
import unittest
import unittest.mock as mock
import urllib.parse
from contextlib import redirect_stdout

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

from keycloak_admin import KeycloakError
from realm import organizations as m

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
WANTED = ROLE_VARS["KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_ROLES"]
FLOW = ROLE_VARS["KEYCLOAK_ORGANIZATION_FLOW"]
MEMBERS = ROLE_VARS["KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_ID"]
EXPORT = ROLE_VARS["KEYCLOAK_EXPORT_CLIENT_ID"]
EXPORT_WANTED = ROLE_VARS["KEYCLOAK_EXPORT_CLIENT_ROLES"]
ROLE_CLIENT = "realm-management"


class FakeRealm:
    """
    Args:
        held: realm-management roles the members service account holds.
        requirement: requirement of the ``organization`` execution.
        export_held: realm-management roles the export service account holds.
    """

    def __init__(
        self, held: list[str], requirement: str, export_held: list[str] | None = None
    ) -> None:
        self.accounts = {MEMBERS: list(held), EXPORT: list(export_held or [])}
        self.executions = [
            {
                "id": "e1",
                "providerId": "conditional-user-configured",
                "requirement": "REQUIRED",
            },
            {"id": "e2", "providerId": "organization", "requirement": requirement},
        ]
        self.writes: list[tuple[str, str]] = []
        self.flow_path = ""

    def call(self, method, path, payload=None, timeout=60):
        route, _, query = path.partition("?")
        if method != "GET":
            self.writes.append((method, route))
        if route == "clients":
            wanted = urllib.parse.parse_qs(query)["clientId"][0]
            return [{"id": f"uuid-{wanted}", "clientId": wanted}], ""
        for client in self.accounts:
            if route == f"clients/uuid-{client}/service-account-user":
                return {"id": f"sa-{client}"}, ""
            if route == f"users/sa-{client}/role-mappings/clients/uuid-{ROLE_CLIENT}":
                return self._mappings(client, method, payload)
        if route.startswith(f"clients/uuid-{ROLE_CLIENT}/roles/"):
            name = urllib.parse.unquote(route.rsplit("/", 1)[1])
            return {"id": f"role-{name}", "name": name}, ""
        if route.startswith("authentication/flows/"):
            self.flow_path = route
            return self._executions(method, payload)
        raise KeycloakError(f"unexpected {method} {route}")

    @property
    def held(self) -> list[str]:
        return self.accounts[MEMBERS]

    def _mappings(self, client, method, payload):
        if method == "GET":
            return [{"id": f"role-{n}", "name": n} for n in self.accounts[client]], ""
        names = [role["name"] for role in payload]
        if method == "POST":
            self.accounts[client] = self.accounts[client] + names
        else:
            self.accounts[client] = [n for n in self.accounts[client] if n not in names]
        return None, ""

    def _executions(self, method, payload):
        if method == "GET":
            return copy.deepcopy(self.executions), ""
        self.executions = [
            payload if e["id"] == payload["id"] else e for e in self.executions
        ]
        return None, ""

    def requirement(self) -> str:
        return next(
            e["requirement"]
            for e in self.executions
            if e["providerId"] == "organization"
        )


def converge(kc: FakeRealm, requirement: str) -> list[str]:
    """
    Args:
        kc: the fake realm.
        requirement: the wanted requirement of the ``organization`` execution.

    Returns:
        The change lines of one run.
    """
    return m.converge_roles(kc, MEMBERS, ROLE_CLIENT, WANTED) + m.converge_execution(
        kc, FLOW, requirement
    )


class TestExistingRealm(unittest.TestCase):
    def test_a_fresh_service_account_gets_exactly_its_two_roles_once(self) -> None:
        kc = FakeRealm([], "ALTERNATIVE")
        lines = converge(kc, "DISABLED")
        self.assertEqual(sorted(kc.held), sorted(WANTED))
        self.assertEqual(kc.requirement(), "DISABLED")
        self.assertEqual(
            lines,
            [
                *(f"granted role {r} to {MEMBERS}" for r in WANTED),
                "updated execution organization DISABLED",
            ],
        )
        self.assertEqual(
            kc.flow_path,
            "authentication/flows/Browser%20-%20Conditional%20Organization/executions",
        )
        kc.writes.clear()
        self.assertEqual(converge(kc, "DISABLED"), [])
        self.assertEqual(kc.writes, [])

    def test_a_drifted_service_account_loses_every_other_role(self) -> None:
        kc = FakeRealm(["manage-users", "manage-realm", "view-users"], "DISABLED")
        lines = converge(kc, "DISABLED")
        self.assertEqual(sorted(kc.held), sorted(WANTED))
        self.assertEqual(
            lines,
            [
                f"granted role manage-organizations to {MEMBERS}",
                f"revoked role manage-realm from {MEMBERS}",
                f"revoked role view-users from {MEMBERS}",
            ],
        )

    def test_the_exactness_check_catches_a_converge_without_revoke(self) -> None:
        kc = FakeRealm(["manage-realm"], "DISABLED")
        original = kc.call

        def without_delete(method, path, payload=None, timeout=60):
            if method == "DELETE":
                return None, ""
            return original(method, path, payload, timeout)

        kc.call = without_delete
        converge(kc, "DISABLED")
        self.assertNotEqual(sorted(kc.held), sorted(WANTED))

    def test_a_flow_without_one_organization_execution_fails(self) -> None:
        kc = FakeRealm([], "ALTERNATIVE")
        kc.executions = kc.executions[:1]
        with self.assertRaises(KeycloakError):
            m.converge_execution(kc, FLOW, "DISABLED")

    def test_main_prints_the_changes_and_their_count(self) -> None:
        kc = FakeRealm(WANTED, "ALTERNATIVE", EXPORT_WANTED)
        self.assertEqual(
            run_main(kc),
            ["updated execution organization DISABLED", "summary changed=1"],
        )

    def test_main_converges_the_export_account_to_exactly_its_read_roles(
        self,
    ) -> None:
        kc = FakeRealm(WANTED, "DISABLED", ["view-users", "manage-users"])
        lines = run_main(kc)
        self.assertEqual(sorted(kc.accounts[EXPORT]), sorted(EXPORT_WANTED))
        self.assertEqual(
            lines,
            [
                f"granted role view-organizations to {EXPORT}",
                f"granted role view-events to {EXPORT}",
                f"revoked role manage-users from {EXPORT}",
                "summary changed=3",
            ],
        )

    def test_the_exactness_check_catches_a_planted_fourth_export_role(self) -> None:
        kc = FakeRealm(WANTED, "DISABLED", [*EXPORT_WANTED, "manage-users"])
        original = kc.call

        def without_delete(method, path, payload=None, timeout=60):
            if method == "DELETE":
                return None, ""
            return original(method, path, payload, timeout)

        kc.call = without_delete
        run_main(kc)
        self.assertNotEqual(sorted(kc.accounts[EXPORT]), sorted(EXPORT_WANTED))


def run_main(kc: FakeRealm) -> list[str]:
    """
    Args:
        kc: the fake realm.

    Returns:
        The output lines of one ``main`` run with the role's service accounts.
    """
    env = {
        "KC_URL": "http://kc",
        "KC_PID": "1",
        "KC_REALM": "example.com",
        "KC_SERVICE_ACCOUNTS": json.dumps({MEMBERS: WANTED, EXPORT: EXPORT_WANTED}),
        "KC_ROLE_CLIENT": ROLE_CLIENT,
        "KC_ORGANIZATION_FLOW": FLOW,
        "KC_ORGANIZATION_REQUIREMENT": "DISABLED",
    }
    out = io.StringIO()
    with (
        mock.patch.dict(m.os.environ, env, clear=True),
        mock.patch.object(m, "container_credentials", lambda path: ("admin", "pw")),
        mock.patch.object(m, "Keycloak", lambda *args: kc),
        redirect_stdout(out),
    ):
        status = m.main()
    if status != 0:
        raise AssertionError(out.getvalue())
    return out.getvalue().splitlines()


if __name__ == "__main__":
    unittest.main()
