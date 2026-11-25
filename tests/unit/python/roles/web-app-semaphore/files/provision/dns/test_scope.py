from __future__ import annotations

import unittest

from .._fake_provision import (  # noqa: TID252  the hyphenated role dir admits no absolute import
    INTERFACE,
    load,
)

dns_scope = load("provision.dns.scope")

ZONE = "ws.example.org"
ZONE_ID = "0123456789abcdef0123456789abcdef"
OTHER_ZONE_ID = "fedcba9876543210fedcba9876543210"
WS_A = "ws-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
WS_B = "ws-9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f"
SCOPE_A = {"workspace": WS_A, "zone": ZONE, "zone_id": ZONE_ID}
OWN = f"shop.{WS_A}.{ZONE}"
FOREIGN = f"shop.{WS_B}.{ZONE}"
RECORD_ID = "372e67954025e0ba6aaa6d586b9e0b59"
WRITTEN_TYPES = ("A", "AAAA", "CNAME")
SUFFIX_TRAPS = (
    f"shop.evil-{WS_A}.{ZONE}",
    f"evil{WS_A}.{ZONE}",
)
NOT_OWN = (
    *SUFFIX_TRAPS,
    f"{WS_A}.{ZONE}",
    f"a.b.{WS_A}.{ZONE}",
    f"shop.{WS_A}.{ZONE}.",
    f"Shop.{WS_A}.{ZONE}",
    f"shop.{WS_A}.{ZONE}.evil.net",
    f"shop.{WS_A}.x{ZONE}",
    f"shop.{WS_A}.example.net",
)


def call(method, **fields):
    """Args:
        method: the HTTP method of the caller's call.
        fields: ``zone_id``, ``record_id``, ``name`` or ``type`` to set, and
            any key a caller may add.

    Returns:
        The request :func:`dns_scope.check` reads, in the zone of ``ws-A``,
        without a record id and without a body unless ``fields`` sets them.
    """
    return {
        "method": method,
        "zone_id": ZONE_ID,
        "record_id": "",
        "name": "",
        "type": "",
        **fields,
    }


def record(name, kind):
    return {"name": name, "type": kind}


def check(request, existing):
    return dns_scope.check(request, SCOPE_A, existing, INTERFACE)


class TestTheCallerWorkspace(unittest.TestCase):
    def test_the_one_dns_policy_of_the_token_names_its_workspace(self) -> None:
        for workspace in (WS_A, WS_B):
            with self.subTest(workspace=workspace):
                self.assertEqual(
                    dns_scope.workspace_of([f"{workspace}-dns"], INTERFACE), workspace
                )

    def test_any_other_token_is_refused(self) -> None:
        for policies in (
            [],
            [f"{WS_A}-dns", "default"],
            [f"{WS_A}-dns", f"{WS_B}-dns"],
            [f"{WS_A}-provision"],
            [f"{WS_A}-transit"],
            [WS_A],
            ["root"],
            ["-dns"],
            [f"{WS_A.upper()}-dns"],
            f"{WS_A}-dns",
            None,
        ):
            with (
                self.subTest(policies=policies),
                self.assertRaises(dns_scope.ScopeError),
            ):
                dns_scope.workspace_of(policies, INTERFACE)


class TestOwnRecords(unittest.TestCase):
    def test_a_create_of_an_own_record_passes(self) -> None:
        for kind in WRITTEN_TYPES:
            with self.subTest(type=kind):
                self.assertIsNone(check(call("POST", name=OWN, type=kind), None))

    def test_a_change_of_an_own_record_passes(self) -> None:
        own = record(OWN, "A")
        for request in (
            call("PUT", record_id=RECORD_ID, name=OWN, type="A"),
            call("PUT", record_id=RECORD_ID, name=OWN, type="AAAA"),
            call("PATCH", record_id=RECORD_ID),
            call("PATCH", record_id=RECORD_ID, name=OWN),
            call("PATCH", record_id=RECORD_ID, type="CNAME"),
        ):
            with self.subTest(request=request):
                self.assertIsNone(check(request, own))

    def test_a_delete_and_a_read_of_an_own_record_pass(self) -> None:
        for method in ("DELETE", "GET"):
            with self.subTest(method=method):
                self.assertIsNone(
                    check(call(method, record_id=RECORD_ID), record(OWN, "CNAME"))
                )


class TestForeignRecords(unittest.TestCase):
    def test_a_create_of_a_record_of_another_workspace_is_refused(self) -> None:
        for kind in WRITTEN_TYPES:
            with self.subTest(type=kind), self.assertRaises(dns_scope.ScopeError):
                check(call("POST", name=FOREIGN, type=kind), None)

    def test_a_change_read_or_delete_of_a_record_of_another_workspace_is_refused(
        self,
    ) -> None:
        foreign = record(FOREIGN, "A")
        for request in (
            call("PUT", record_id=RECORD_ID, name=FOREIGN, type="A"),
            call("PUT", record_id=RECORD_ID, name=OWN, type="A"),
            call("PATCH", record_id=RECORD_ID),
            call("PATCH", record_id=RECORD_ID, name=OWN),
            call("DELETE", record_id=RECORD_ID),
            call("GET", record_id=RECORD_ID),
        ):
            with self.subTest(request=request), self.assertRaises(dns_scope.ScopeError):
                check(request, foreign)

    def test_an_own_record_cannot_be_renamed_into_another_workspace(self) -> None:
        with self.assertRaises(dns_scope.ScopeError):
            check(call("PATCH", record_id=RECORD_ID, name=FOREIGN), record(OWN, "A"))

    def test_a_workspace_the_request_names_never_widens_the_scope(self) -> None:
        with self.assertRaises(dns_scope.ScopeError):
            check(call("POST", name=FOREIGN, type="A", workspace=WS_B), None)

    def test_a_record_of_another_zone_is_refused(self) -> None:
        with self.assertRaises(dns_scope.ScopeError):
            check(call("POST", zone_id=OTHER_ZONE_ID, name=OWN, type="A"), None)
        with self.assertRaises(dns_scope.ScopeError):
            dns_scope.check(
                call("POST", name=OWN, type="A"),
                {**SCOPE_A, "zone_id": ""},
                None,
                INTERFACE,
            )


class TestNamesThatOnlyEndLikeAnOwnName(unittest.TestCase):
    def test_no_such_name_is_owned_or_created(self) -> None:
        for name in NOT_OWN:
            with self.subTest(name=name):
                self.assertFalse(dns_scope.owns(name, SCOPE_A, INTERFACE))
                with self.assertRaises(dns_scope.ScopeError):
                    check(call("POST", name=name, type="A"), None)

    def test_control_a_check_without_the_dot_before_the_workspace_admits_them(
        self,
    ) -> None:
        for name in SUFFIX_TRAPS:
            with self.subTest(name=name):
                self.assertTrue(name.endswith(f"{WS_A}.{ZONE}"))
                self.assertFalse(dns_scope.owns(name, SCOPE_A, INTERFACE))

    def test_control_the_own_name_is_owned(self) -> None:
        self.assertTrue(dns_scope.owns(OWN, SCOPE_A, INTERFACE))


class TestTypesAndOperations(unittest.TestCase):
    def test_a_type_no_dns_module_writes_is_refused(self) -> None:
        for request, existing in (
            (call("POST", name=OWN, type="TXT"), None),
            (call("POST", name=OWN, type="NS"), None),
            (call("POST", name=OWN, type=""), None),
            (call("PATCH", record_id=RECORD_ID, type="MX"), record(OWN, "A")),
            (call("DELETE", record_id=RECORD_ID), record(OWN, "TXT")),
        ):
            with (
                self.subTest(request=request, existing=existing),
                self.assertRaises(dns_scope.ScopeError),
            ):
                check(request, existing)

    def test_an_operation_the_broker_does_not_forward_is_refused(self) -> None:
        own = record(OWN, "A")
        for request, existing in (
            (call("POST", record_id=RECORD_ID, name=OWN, type="A"), None),
            (call("POST", name=OWN, type="A"), own),
            (call("PUT", name=OWN, type="A"), None),
            (call("PATCH", record_id=RECORD_ID), None),
            (call("PUT", record_id=RECORD_ID, name=OWN), own),
            (call("DELETE", record_id=RECORD_ID, name=OWN), own),
            (call("GET", record_id=RECORD_ID, type="A"), own),
            (call("GET"), None),
            (call("HEAD", record_id=RECORD_ID), own),
            (call("OPTIONS"), None),
        ):
            with self.subTest(request=request), self.assertRaises(dns_scope.ScopeError):
                check(request, existing)


if __name__ == "__main__":
    unittest.main()
