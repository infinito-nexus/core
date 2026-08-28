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


if __name__ == "__main__":
    unittest.main()
