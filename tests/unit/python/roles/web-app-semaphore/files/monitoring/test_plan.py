from __future__ import annotations

import ipaddress
import unittest

from ._fake_monitoring import (
    DOCUMENTATION,
    HOST_KEY,
    ID,
    WS,
    RefusalError,
    inventory,
    planned_for,
    planner,
    public,
    removed_plan,
    rules,
    target,
)

GLOBAL_HOST = "192.0.1.1"
GLOBAL_ANSWERS = ["172.32.0.1", "2001:200::1"]


class TestThePlan(unittest.TestCase):
    def test_only_monitor_host_is_planned(self) -> None:
        planned = planned_for(
            "target", target=target(), other=target(primary="other.example.org")
        )
        self.assertEqual(planned["host"], "target")
        self.assertEqual(
            planned["entry"]["domains"],
            ["prometheus.target.example.org", "target.example.org"],
        )

    def test_a_host_outside_the_inventory_refuses(self) -> None:
        with self.assertRaises(RefusalError):
            planned_for("ghost", target=target())

    def test_remove_plans_no_entry(self) -> None:
        self.assertIsNone(removed_plan()["entry"])

    def test_no_value_falls_back(self) -> None:
        for broken in (
            {key: value for key, value in target().items() if key != "ansible_host"},
            {
                key: value
                for key, value in target().items()
                if key not in ("applications", "DOMAIN_PRIMARY")
            },
            {key: value for key, value in target().items() if key != "ansible_user"},
            {key: value for key, value in target().items() if key != "ssh_host_key"},
        ):
            with (
                self.subTest(keys=sorted(broken)),
                self.assertRaises(RefusalError),
            ):
                planned_for(target=broken)

    def test_the_federation_domain_is_derived_like_the_deploy_without_a_pin(
        self,
    ) -> None:
        unpinned = {
            key: value for key, value in target().items() if key != "applications"
        }
        self.assertEqual(
            planned_for(target=unpinned)["entry"]["federation"],
            "prometheus.target.example.org",
        )

    def federation_of(self, domain):
        pinned = target(
            applications={
                "web-app-prometheus": {"server": {"domains": {"canonical": [domain]}}}
            }
        )
        return planned_for(target=pinned)["entry"]["federation"]

    def test_a_pin_inside_the_primary_domain_wins_over_the_derived_one(self) -> None:
        self.assertEqual(
            self.federation_of("metrics.target.example.org"),
            "metrics.target.example.org",
        )

    def test_negative_control_the_bearer_never_goes_to_a_store_picked_host(
        self,
    ) -> None:
        self.assertEqual(
            self.federation_of("metrics.example.net"), "prometheus.target.example.org"
        )

    def test_negative_control_no_primary_domain_refuses(self) -> None:
        bare = {
            key: value
            for key, value in target().items()
            if key not in ("applications", "DOMAIN_PRIMARY")
        }
        with self.assertRaisesRegex(
            RefusalError, "deploy domain of target is no lowercase domain"
        ):
            planned_for(target=bare)

    def test_negative_control_an_inventory_domain_primary_is_ignored(self) -> None:
        entry = planned_for(
            target=target(
                DOMAIN_PRIMARY="evil.example.net",
                applications={},
            ),
            primary="target.example.org",
        )["entry"]
        self.assertEqual(entry["federation"], "prometheus.target.example.org")
        self.assertEqual(entry["domains"], ["target.example.org"])

    def test_a_host_without_the_kinds_needs_no_access_or_federation(self) -> None:
        quiet = {
            key: value
            for key, value in target().items()
            if key not in ("ansible_user", "ssh_host_key", "applications")
        }
        quiet["platform_monitoring"] = {
            "agent": False,
            "health": False,
            "system": False,
            "traffic": False,
        }
        entry = planned_for(target=quiet)["entry"]
        self.assertEqual(
            (entry["ssh"], entry["federation"], entry["prometheus"]),
            (None, None, False),
        )

    def test_every_name_and_domain_is_checked(self) -> None:
        for broken in (
            target(ansible_host="192.0.2.10; rm -rf /"),
            target(primary="Target.Example.org"),
            target(primary="target.example.org/x"),
            target(ansible_user="-oProxyCommand=x"),
            target(ssh_host_key="ssh-ed25519 AAAA\nssh-rsa BBBB"),
            target(ssh_host_key="ssh-dss AAAA"),
            target(ansible_port="22 -o x"),
            target(
                applications={
                    "web-app-prometheus": {
                        "server": {"domains": {"canonical": ["x..y"]}}
                    }
                }
            ),
        ):
            with (
                self.subTest(broken=broken),
                self.assertRaises(RefusalError),
            ):
                planned_for(target=broken)

    def test_an_ipv6_address_is_accepted_and_normalised(self) -> None:
        entry = planned_for(target=target(ansible_host="2001:DB8::1"))["entry"]
        self.assertEqual(entry["address"], "2001:db8::1")

    def test_the_ssh_access_comes_from_the_inventory(self) -> None:
        entry = planned_for(target=target(ansible_port=2222))["entry"]
        self.assertEqual(
            entry["ssh"],
            {
                "user": "deploy",
                "port": "2222",
                "key_type": "ssh-ed25519",
                "key": HOST_KEY.split()[1],
            },
        )

    def test_the_share_schema_refuses_unknown_keys(self) -> None:
        for value in ({"logs": True}, {"agent": "no"}, ["agent"]):
            with self.subTest(value=value), self.assertRaises(RefusalError):
                planned_for(target=target(value))

    def test_an_internal_address_or_domain_is_refused(self) -> None:
        for broken in (
            target(ansible_host="127.1"),
            target(ansible_host="10.0.0.5"),
            target(ansible_host="0x7f000001"),
            target(ansible_host="::ffff:169.254.169.254"),
            target(ansible_host="fd12:3456::1"),
            target(ansible_host="100.64.0.1"),
            target(primary="app.localhost"),
        ):
            with (
                self.subTest(broken=broken),
                self.assertRaisesRegex(RefusalError, "internal address"),
            ):
                planned_for(target=broken)

    def test_the_test_variant_opens_its_own_network_only(self) -> None:
        private = [ipaddress.ip_network("172.30.0.0/16")]

        def own(_name):
            return ["172.30.0.8"]

        entry = planned_for(
            target=target(ansible_host="172.30.0.7"), private=private, resolver=own
        )["entry"]
        self.assertEqual(entry["address"], "172.30.0.7")
        for address in ("10.0.0.5", "127.0.0.1", "192.0.2.10"):
            with (
                self.subTest(address=address),
                self.assertRaisesRegex(RefusalError, "internal address"),
            ):
                planned_for(
                    target=target(ansible_host=address), private=private, resolver=own
                )

    def test_a_name_resolving_inward_is_refused(self) -> None:
        for answer in (["10.0.0.5"], ["203.0.113.10", "::1"], ["169.254.169.254"]):
            with (
                self.subTest(answer=answer),
                self.assertRaisesRegex(RefusalError, "internal address"),
            ):
                planned_for(
                    target=target(ansible_host="host.example.org"),
                    resolver=lambda _name, answer=answer: answer,
                )

    def test_a_domain_resolving_inward_is_refused(self) -> None:
        def resolver(name):
            return ["10.0.0.5"] if name.startswith("prometheus.") else public(name)

        with self.assertRaisesRegex(
            RefusalError,
            r"a domain of target prometheus\.target\.example\.org is an internal"
            r" address \(10\.0\.0\.5\)",
        ):
            planned_for(resolver=resolver)

    def test_an_unresolvable_name_refuses_unless_the_variant_opens_a_network(
        self,
    ) -> None:
        with self.assertRaisesRegex(RefusalError, "resolves to no address"):
            planned_for(resolver=lambda _name: [], private=())
        entry = planned_for(resolver=lambda _name: [])["entry"]
        self.assertEqual(entry["address"], "192.0.2.10")

    def test_a_documentation_address_is_internal_without_the_variant(self) -> None:
        for broken, resolver in (
            (target(), public),
            (target(ansible_host="2001:db8::1"), public),
            (target(ansible_host=GLOBAL_HOST), public),
            (target(ansible_host=GLOBAL_HOST), lambda _name: ["198.51.100.7"]),
        ):
            with (
                self.subTest(broken=broken["ansible_host"]),
                self.assertRaisesRegex(RefusalError, "internal address"),
            ):
                planned_for(target=broken, private=(), resolver=resolver)

    def test_negative_control_a_global_address_passes_without_the_variant(
        self,
    ) -> None:
        entry = planned_for(
            target=target(ansible_host=GLOBAL_HOST),
            private=(),
            resolver=lambda _name: GLOBAL_ANSWERS,
        )["entry"]
        self.assertEqual(entry["address"], GLOBAL_HOST)

    def test_negative_control_a_public_answer_passes(self) -> None:
        asked = []
        planned_for(
            target=target(ansible_host="host.example.org"),
            resolver=lambda name: asked.append(name) or public(name),
        )
        self.assertEqual(
            sorted(asked),
            [
                "host.example.org",
                "prometheus.target.example.org",
                "prometheus.target.example.org",
                "target.example.org",
            ],
        )

    def test_checkmk_gets_the_checked_address_not_a_later_answer(self) -> None:
        answers = iter([["2001:db8::7", "203.0.113.10"], ["10.0.0.5"]])

        def rebinding(name):
            return next(answers) if name == "host.example.org" else public(name)

        entry = planned_for(
            target=target(ansible_host="host.example.org"), resolver=rebinding
        )["entry"]
        self.assertEqual(entry["address"], "203.0.113.10")
        self.assertEqual(
            rules.host_attributes(WS, "target", entry)["ipaddress"],
            "203.0.113.10",
        )
        self.assertEqual(next(answers), ["10.0.0.5"])

    def test_negative_control_a_literal_and_an_unresolved_variant_name_stay(
        self,
    ) -> None:
        self.assertEqual(planned_for()["entry"]["address"], "192.0.2.10")
        entry = planned_for(
            target=target(ansible_host="host.example.org"), resolver=lambda _name: []
        )["entry"]
        self.assertEqual(entry["address"], "host.example.org")

    def test_only_workspace_domains_are_checked_over_https(self) -> None:
        third = target(
            applications={
                "web-app-prometheus": {
                    "server": {
                        "domains": {
                            "canonical": [
                                "victim.example.net",
                                "prometheus.example.org",
                            ]
                        }
                    }
                }
            }
        )
        self.assertEqual(
            planned_for(target=third)["entry"]["domains"],
            ["prometheus.example.org", "target.example.org"],
        )

    def test_apply_plans_the_label_remove_none(self) -> None:
        self.assertEqual(planned_for()["label"], "target")
        self.assertIsNone(removed_plan()["label"])

    def test_an_ipv6_scope_id_is_refused_in_the_inventory_host(self) -> None:
        for address in ("fe80::1%a:b", "fe80::1%a_b", "2001:db8::1%eth0"):
            with (
                self.subTest(address=address),
                self.assertRaisesRegex(RefusalError, "scope id"),
            ):
                planned_for(target=target(ansible_host=address))


class TestTheWorkerFederation(unittest.TestCase):
    def plan(self, host, stack):
        primary = f"{host}.example.org"
        return planner.plan(ID, "apply", host, stack, DOCUMENTATION, primary, public)

    def test_only_the_stack_host_federates(self) -> None:
        hosts = {"target": target(), "manager": target(primary="manager.example.org")}
        stack = {**inventory(**hosts), "svc-swarm-manager": {"hosts": ["manager"]}}
        with self.assertRaisesRegex(RefusalError, "target is a worker of manager"):
            self.plan("target", stack)
        self.assertTrue(self.plan("manager", stack)["entry"]["prometheus"])
        quiet = dict.fromkeys(("health", "system", "traffic"), False)
        stack["_meta"]["hostvars"]["target"] = target(quiet)
        self.assertFalse(self.plan("target", stack)["entry"]["prometheus"])


if __name__ == "__main__":
    unittest.main()
