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


if __name__ == "__main__":
    unittest.main()
