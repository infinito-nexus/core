import sys
import unittest

from . import PROJECT_ROOT


def _ensure_repo_root_on_syspath():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


_ensure_repo_root_on_syspath()

from plugins.lookup.container_dns import resolve_container_dns  # noqa: E402

_BRIDGE = {"docker0": {"ipv4": {"address": "172.17.0.1"}}}
_CLEARNET = {"internet": {"dns": "172.30.0.53"}}


def _vars(**overrides):
    variables = {
        "ansible_facts": _BRIDGE,
        "group_names": ["svc-net-tor"],
        "networks": _CLEARNET,
        "DEPLOYMENT_MODE": "compose",
    }
    variables.update(overrides)
    return variables


class TestResolveContainerDns(unittest.TestCase):
    """The bridge resolver must come first on a Tor node so .onion resolves,
    with the clearnet resolver kept as fallback."""

    def test_tor_node_prefers_the_bridge_resolver(self):
        self.assertEqual(resolve_container_dns(_vars()), ["172.17.0.1", "172.30.0.53"])

    def test_without_tor_only_clearnet(self):
        self.assertEqual(resolve_container_dns(_vars(group_names=[])), ["172.30.0.53"])

    def test_the_bridge_follows_ownership_not_the_deploy_mode(self):
        self.assertEqual(
            resolve_container_dns(_vars(DEPLOYMENT_MODE="swarm")),
            ["172.17.0.1", "172.30.0.53"],
        )

    def test_a_tor_node_without_clearnet_keeps_the_bridge(self):
        self.assertEqual(
            resolve_container_dns(_vars(DEPLOYMENT_MODE="swarm", networks={})),
            ["172.17.0.1"],
        )

    def test_a_non_tor_node_yields_nothing_without_clearnet(self):
        self.assertEqual(resolve_container_dns(_vars(group_names=[], networks={})), [])

    def test_a_bridge_equal_to_clearnet_is_not_emitted_twice(self):
        self.assertEqual(
            resolve_container_dns(_vars(networks={"internet": {"dns": "172.17.0.1"}})),
            ["172.17.0.1"],
        )

    def test_without_bridge_only_clearnet(self):
        self.assertEqual(
            resolve_container_dns(_vars(ansible_facts={})), ["172.30.0.53"]
        )

    def test_without_clearnet_only_bridge(self):
        self.assertEqual(resolve_container_dns(_vars(networks={})), ["172.17.0.1"])

    def test_nothing_configured_yields_empty_list(self):
        self.assertEqual(
            resolve_container_dns(_vars(ansible_facts={}, networks={})), []
        )

    def test_missing_keys_do_not_raise(self):
        self.assertEqual(resolve_container_dns({}), [])


class TestLoopbackOnlyHost(unittest.TestCase):
    """A host resolving through its own loopback listener cannot hand that
    address to containers, because docker drops loopback entries."""

    @staticmethod
    def _facts(nameservers):
        return {**_BRIDGE, "dns": {"nameservers": nameservers}}

    def test_a_loopback_only_host_prefers_the_bridge_without_tor(self):
        self.assertEqual(
            resolve_container_dns(
                _vars(group_names=[], ansible_facts=self._facts(["127.0.0.1"]))
            ),
            ["172.17.0.1", "172.30.0.53"],
        )

    def test_ipv6_loopback_counts_the_same(self):
        self.assertEqual(
            resolve_container_dns(
                _vars(group_names=[], ansible_facts=self._facts(["::1"]))
            ),
            ["172.17.0.1", "172.30.0.53"],
        )

    def test_a_routable_resolver_alongside_loopback_needs_no_bridge(self):
        self.assertEqual(
            resolve_container_dns(
                _vars(
                    group_names=[],
                    ansible_facts=self._facts(["127.0.0.1", "172.30.0.53"]),
                )
            ),
            ["172.30.0.53"],
        )

    def test_a_routable_host_resolver_needs_no_bridge(self):
        self.assertEqual(
            resolve_container_dns(
                _vars(group_names=[], ansible_facts=self._facts(["172.30.0.53"]))
            ),
            ["172.30.0.53"],
        )

    def test_an_empty_nameserver_list_is_not_loopback_only(self):
        self.assertEqual(
            resolve_container_dns(_vars(group_names=[], ansible_facts=self._facts([]))),
            ["172.30.0.53"],
        )


class _Templar:
    """Renders one expression, the way a play's templar would."""

    def __init__(self, mapping):
        self.mapping = mapping

    def template(self, text):
        for name, value in self.mapping.items():
            if text.strip() == "{{ " + name + " | first }}":
                return value[0]
        return text


class TestInventoryExpressionIsRendered(unittest.TestCase):
    """The field arrives through `-e @inventory.yml` and is read raw.

    While it held a literal address nobody noticed that nothing rendered it.
    An expression there reached the daemon as its own source text, and docker
    refused the whole config: ParseAddr("{{ ... }}"): unable to parse IP.
    """

    EXPRESSION = "{{ NETWORK_PUBLIC_DNS_RESOLVERS | first }}"

    def facts(self, nameservers):
        return {"dns": {"nameservers": nameservers}, "docker0": {"ipv4": {}}}

    def test_an_expression_is_resolved_against_the_play(self):
        templar = _Templar({"NETWORK_PUBLIC_DNS_RESOLVERS": ["192.0.2.1", "192.0.2.2"]})
        result = resolve_container_dns(
            {
                "networks": {"internet": {"dns": self.EXPRESSION}},
                "group_names": [],
                "ansible_facts": self.facts(["192.0.2.9"]),
            },
            templar,
        )
        self.assertEqual(["192.0.2.1"], result)

    def test_no_resolver_ever_carries_jinja(self):
        """What reaches daemon.json must be an address, not its source text."""
        templar = _Templar({"NETWORK_PUBLIC_DNS_RESOLVERS": ["192.0.2.1"]})
        for nameservers in ([], ["127.0.0.1"], ["192.0.2.9"]):
            with self.subTest(nameservers=nameservers):
                for resolver in resolve_container_dns(
                    {
                        "networks": {"internet": {"dns": self.EXPRESSION}},
                        "group_names": [],
                        "ansible_facts": self.facts(nameservers),
                    },
                    templar,
                ):
                    self.assertNotIn("{{", resolver)

    def test_a_literal_survives_without_a_templar(self):
        """Outside a play there is nothing to render against, and no need."""
        self.assertEqual(
            ["172.30.0.53"],
            resolve_container_dns(
                {
                    "networks": {"internet": {"dns": "172.30.0.53"}},
                    "group_names": [],
                    "ansible_facts": self.facts(["192.0.2.9"]),
                }
            ),
        )

    def test_an_unresolvable_expression_aborts_instead_of_reaching_docker(self):
        """This is the shape that reached CI: no templar, so nothing rendered."""
        with self.assertRaises(Exception) as caught:
            resolve_container_dns(
                {
                    "networks": {"internet": {"dns": self.EXPRESSION}},
                    "group_names": [],
                    "ansible_facts": self.facts(["192.0.2.9"]),
                }
            )
        self.assertIn("daemon.json", str(caught.exception))

    def test_a_templar_that_cannot_resolve_it_aborts_too(self):
        with self.assertRaises(Exception):
            resolve_container_dns(
                {
                    "networks": {"internet": {"dns": self.EXPRESSION}},
                    "group_names": [],
                    "ansible_facts": self.facts(["192.0.2.9"]),
                },
                _Templar({}),
            )


if __name__ == "__main__":
    unittest.main()
