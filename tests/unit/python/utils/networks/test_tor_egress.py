"""Matching, precedence and validation of the Tor egress lists.

The route decides only what no list matches, ``except`` only narrows its own
``include``, and a destination both lists keep takes Tor. A host-name entry
covers its subdomains, because that is the only match dnsmasq can carry.
"""

from __future__ import annotations

import unittest

from utils.networks.tor_egress import (
    DIRECT,
    TOR,
    address_path,
    admitted,
    dns_rules,
    host_path,
    literal_overlaps,
    literal_sets,
    parse_entry,
    parse_lists,
    plan,
    role_subnets,
    violations,
)

INFRASTRUCTURE = {"mirrors": [], "ntp": [], "registry_blob_hosts": {}, "acme": []}


def _egress(tor=(), tor_except=(), direct=(), direct_except=()):
    return {
        "route": "onion",
        "tor": {"include": list(tor), "except": list(tor_except)},
        "direct": {"include": list(direct), "except": list(direct_except)},
        "infrastructure": dict(INFRASTRUCTURE),
    }


class TestEntries(unittest.TestCase):
    def test_a_wildcard_and_a_bare_name_cover_the_same_tree(self) -> None:
        self.assertEqual(parse_entry("*.Example.org.").domain, "example.org")
        self.assertEqual(parse_entry("example.org").domain, "example.org")

    def test_addresses_and_cidrs_parse_as_networks(self) -> None:
        self.assertEqual(str(parse_entry("10.1.2.3").network), "10.1.2.3/32")
        self.assertEqual(str(parse_entry("2001:db8::/32").network), "2001:db8::/32")

    def test_a_wildcard_inside_a_name_is_refused(self) -> None:
        for raw in (
            "a.*.example.org",
            "*example.org",
            "**.example.org",
            "",
            "exa mple.org",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_entry(raw)

    def test_a_cidr_with_host_bits_is_refused_not_widened(self) -> None:
        with self.assertRaisesRegex(ValueError, "host bits"):
            parse_entry("192.0.2.7/24")

    def test_a_mistyped_address_is_not_taken_for_a_host_name(self) -> None:
        for raw in ("10.0.0.256", "1.2.3", "192.0.2.1.5"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_entry(raw)
        self.assertEqual(parse_entry("1password.com").domain, "1password.com")


class TestMatching(unittest.TestCase):
    def test_a_name_covers_its_subdomains_but_not_a_sibling_suffix(self) -> None:
        lists = parse_lists(_egress(direct=["*.example.org"]))
        self.assertEqual(host_path("all", lists, "example.org"), DIRECT)
        self.assertEqual(host_path("all", lists, "a.b.example.org"), DIRECT)
        self.assertEqual(host_path("all", lists, "badexample.org"), TOR)

    def test_except_removes_matches_from_its_own_include(self) -> None:
        lists = parse_lists(
            _egress(direct=["*.example.org"], direct_except=["cdn.example.org"])
        )
        self.assertEqual(host_path("all", lists, "www.example.org"), DIRECT)
        self.assertEqual(host_path("all", lists, "x.cdn.example.org"), TOR)

    def test_except_does_not_reach_into_the_other_list(self) -> None:
        lists = parse_lists(
            _egress(
                tor=["example.org"],
                direct=["example.org"],
                direct_except=["example.org"],
            )
        )
        self.assertEqual(host_path("none", lists, "example.org"), TOR)

    def test_a_destination_in_both_lists_takes_tor(self) -> None:
        lists = parse_lists(
            _egress(tor=["secret.example.org"], direct=["*.example.org"])
        )
        self.assertEqual(host_path("all", lists, "secret.example.org"), TOR)
        self.assertEqual(host_path("onion", lists, "secret.example.org"), TOR)
        self.assertEqual(host_path("all", lists, "www.example.org"), DIRECT)

    def test_the_route_decides_what_no_list_matches(self) -> None:
        lists = parse_lists(_egress())
        self.assertEqual(host_path("none", lists, "example.org"), DIRECT)
        self.assertEqual(host_path("onion", lists, "example.org"), DIRECT)
        self.assertEqual(host_path("onion", lists, "abc.onion"), TOR)
        self.assertEqual(host_path("all", lists, "example.org"), TOR)

    def test_address_entries_match_by_network_with_excepts(self) -> None:
        lists = parse_lists(
            _egress(direct=["192.0.2.0/24"], direct_except=["192.0.2.7"])
        )
        self.assertEqual(address_path("all", lists, "192.0.2.8"), DIRECT)
        self.assertEqual(address_path("all", lists, "192.0.2.7"), TOR)
        self.assertEqual(address_path("onion", lists, "198.51.100.1"), DIRECT)

    def test_literal_sets_subtract_the_excepts(self) -> None:
        sets = literal_sets(
            parse_lists(_egress(direct=["192.0.2.0/30"], direct_except=["192.0.2.1"]))
        )
        self.assertEqual(sets["direct_v4"], ["192.0.2.0", "192.0.2.2/31"])
        self.assertEqual(sets["tor_v4"], [])

    def test_address_excepts_get_a_set_of_their_own(self) -> None:
        sets = literal_sets(
            parse_lists(
                _egress(
                    direct=["*.docker.io"],
                    direct_except=["203.0.113.7", "evil.docker.io", "2001:db8::1"],
                )
            )
        )
        self.assertEqual(sets["direct_except_v4"], ["203.0.113.7"])
        self.assertEqual(sets["direct_except_v6"], ["2001:db8::1"])


class TestAdmission(unittest.TestCase):
    def test_admitted_names_only_the_addresses_inside_the_ranges(self) -> None:
        self.assertEqual(
            admitted(
                ["172.30.0.53", "127.0.0.1", "::1"], ["127.0.0.0/8", "172.17.0.1"]
            ),
            ["127.0.0.1"],
        )

    def test_role_subnets_are_those_of_the_deployed_roles(self) -> None:
        applications = {
            "web-app-bigbluebutton": {"networks": {"local": {"subnet": "10.7.7.0/24"}}},
            "web-app-nextcloud": {"networks": {"local": {"subnet": "192.168.10.0/28"}}},
            "svc-net-tor": {"networks": {}},
        }
        self.assertEqual(
            role_subnets(
                applications, ["web-app-bigbluebutton", "svc-net-tor", "unknown"]
            ),
            ["10.7.7.0/24"],
        )


class TestDnsRules(unittest.TestCase):
    def test_onion_renders_nothing_for_names_that_already_go_direct(self) -> None:
        lists = parse_lists(_egress(direct=["deb.debian.org", "docker.io"]))
        self.assertEqual(dns_rules("onion", lists), [])

    def test_all_renders_every_direct_name(self) -> None:
        lists = parse_lists(_egress(direct=["deb.debian.org", "docker.io"]))
        self.assertEqual(
            dns_rules("all", lists),
            [
                {"domain": "deb.debian.org", "path": DIRECT},
                {"domain": "docker.io", "path": DIRECT},
            ],
        )

    def test_a_carve_out_renders_below_its_parent(self) -> None:
        lists = parse_lists(
            _egress(direct=["*.example.org"], direct_except=["cdn.example.org"])
        )
        self.assertEqual(
            dns_rules("all", lists),
            [
                {"domain": "cdn.example.org", "path": TOR},
                {"domain": "example.org", "path": DIRECT},
            ],
        )

    def test_a_broader_except_swallows_a_narrower_include(self) -> None:
        lists = parse_lists(
            _egress(direct=["api.example.org"], direct_except=["*.example.org"])
        )
        self.assertEqual(dns_rules("all", lists), [])

    def test_every_name_gets_the_path_of_its_deepest_rule(self) -> None:
        """dnsmasq applies the longest matching domain; the rules must agree with host_path."""
        egress = _egress(
            tor=["secret.example.org", "net.example"],
            tor_except=["open.net.example"],
            direct=["*.example.org", "example.net", "*.net.example"],
            direct_except=["cdn.example.org"],
        )
        lists = parse_lists(egress)
        names = [
            "example.org",
            "www.example.org",
            "cdn.example.org",
            "a.cdn.example.org",
            "secret.example.org",
            "x.secret.example.org",
            "net.example",
            "open.net.example",
            "a.open.net.example",
            "example.net",
            "unlisted.test",
        ]
        for route in ("onion", "all"):
            rules = {rule["domain"]: rule["path"] for rule in dns_rules(route, lists)}
            for name in names:
                covering = [d for d in rules if name == d or name.endswith("." + d)]
                applied = (
                    rules[max(covering, key=len)]
                    if covering
                    else ("tor" if route == "all" else "direct")
                )
                with self.subTest(route=route, name=name):
                    self.assertEqual(applied, host_path(route, lists, name))


class TestPlan(unittest.TestCase):
    def test_automap_stays_onion_only_while_no_clearnet_name_reaches_tor(self) -> None:
        self.assertFalse(plan(_egress(direct=["docker.io"]), "onion")["automap_all"])
        self.assertTrue(plan(_egress(tor=["example.org"]), "onion")["automap_all"])
        self.assertTrue(plan(_egress(), "all")["automap_all"])

    def test_an_unknown_route_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            plan(_egress(), "everything")


class TestViolations(unittest.TestCase):
    def test_a_valid_configuration_has_none(self) -> None:
        self.assertEqual(violations(_egress(direct=["docker.io"]), "all", False), [])
        self.assertEqual(violations(_egress(), "none", True), [])

    def test_an_unknown_route_is_refused_at_deploy(self) -> None:
        found = violations(_egress(), "everything", False)
        self.assertEqual(len(found), 1)
        self.assertIn("egress.route must be one of", found[0])

    def test_lists_under_none_are_refused(self) -> None:
        found = violations(_egress(direct=["docker.io"]), "none", False)
        self.assertEqual(len(found), 1)
        self.assertIn("direct.include", found[0])

    def test_onion_cannot_go_direct(self) -> None:
        for raw in ("abc.onion", "*.onion", "onion"):
            with self.subTest(raw=raw):
                self.assertTrue(violations(_egress(direct=[raw]), "all", False))

    def test_all_is_refused_in_swarm(self) -> None:
        (found,) = violations(_egress(), "all", True)
        self.assertIn("the egress router runs on the managers only", found)
        self.assertNotIn("namespace", found)
        self.assertEqual(violations(_egress(), "onion", True), [])

    def test_a_malformed_entry_or_block_is_reported(self) -> None:
        self.assertTrue(violations(_egress(tor=["a.*.b"]), "onion", False))
        broken = _egress()
        broken["tor"] = {"include": []}
        self.assertTrue(violations(broken, "onion", False))
        self.assertTrue(violations(_egress(), "sometimes", False))

    def test_the_removed_enabled_key_is_refused(self) -> None:
        for value in (True, False):
            egress = _egress()
            egress["enabled"] = value
            with self.subTest(enabled=value):
                found = violations(egress, "onion", False)
                self.assertEqual(len(found), 1)
                self.assertIn("egress.enabled was replaced by egress.route", found[0])

    def test_an_unknown_key_is_refused(self) -> None:
        egress = _egress()
        egress["routes"] = "all"
        self.assertIn("unknown keys routes", violations(egress, "onion", False)[0])

    def test_a_misshapen_infrastructure_block_is_refused(self) -> None:
        missing = _egress()
        del missing["infrastructure"]
        self.assertTrue(violations(missing, "onion", False))
        wrong = _egress()
        wrong["infrastructure"]["registry_blob_hosts"] = ["docker.io"]
        found = violations(wrong, "onion", False)
        self.assertEqual(len(found), 1)
        self.assertIn("registry_blob_hosts", found[0])

    def test_literal_overlaps_are_reported(self) -> None:
        self.assertEqual(
            literal_overlaps(
                _egress(
                    tor=["Example.org", "10.0.0.1"],
                    direct=["*.example.org", "10.0.0.1/32", "docker.io"],
                )
            ),
            ["*.example.org", "10.0.0.1/32"],
        )
        self.assertEqual(
            literal_overlaps(_egress(tor=["a.example.org"], direct=["example.org"])), []
        )


if __name__ == "__main__":
    unittest.main()
