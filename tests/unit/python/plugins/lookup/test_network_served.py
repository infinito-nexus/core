import unittest

from ansible.errors import AnsibleError

import plugins.lookup.network_served as served_mod


class TestNetworkServedLookup(unittest.TestCase):
    def _run(self, name, **variables):
        return served_mod.LookupModule().run([name], variables=variables)[0]

    def test_a_node_without_tor_serves_clearnet_only(self):
        self.assertTrue(self._run("clearnet", group_names=["web-app-x"]))
        self.assertFalse(self._run("tor", group_names=["web-app-x"]))

    def test_a_tor_node_without_a_mode_serves_both(self):
        self.assertTrue(self._run("clearnet", group_names=["svc-net-tor"]))
        self.assertTrue(self._run("tor", group_names=["svc-net-tor"]))

    def test_a_tor_only_node_drops_clearnet(self):
        self.assertFalse(
            self._run("clearnet", group_names=["svc-net-tor"], NETWORK_MODE="tor")
        )

    def test_a_tor_node_pinned_to_clearnet_drops_tor(self):
        self.assertFalse(
            self._run("tor", group_names=["svc-net-tor"], NETWORK_MODE="clearnet")
        )

    def test_a_named_role_must_be_deployed(self):
        lookup = served_mod.LookupModule()
        variables = {"group_names": ["svc-net-tor", "web-app-keycloak"]}
        self.assertTrue(
            lookup.run(["clearnet", "web-app-keycloak"], variables=variables)[0]
        )
        self.assertFalse(
            lookup.run(["clearnet", "web-app-dashboard"], variables=variables)[0]
        )

    def test_a_deployed_role_on_a_tor_only_node_stays_off(self):
        lookup = served_mod.LookupModule()
        variables = {
            "group_names": ["svc-net-tor", "web-app-keycloak"],
            "NETWORK_MODE": "tor",
        }
        self.assertFalse(
            lookup.run(["clearnet", "web-app-keycloak"], variables=variables)[0]
        )

    def test_a_mode_the_node_cannot_serve_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run("clearnet", group_names=["web-app-x"], NETWORK_MODE="tor")

    def test_an_unknown_network_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run("handshake", group_names=["svc-net-tor"])


if __name__ == "__main__":
    unittest.main()
