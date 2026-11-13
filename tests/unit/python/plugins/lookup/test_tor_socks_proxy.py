from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader

from plugins.lookup.tor_socks_proxy import LookupModule, resolve_proxy_url

APPS = {"svc-net-tor": {"services": {"tor": {"ports": {"local": {"socks": 9050}}}}}}


class TestResolveProxyUrl(unittest.TestCase):
    def test_a_container_reaches_the_tor_daemon_of_its_own_node(self):
        self.assertEqual(resolve_proxy_url(APPS), "socks5h://host.docker.internal:9050")

    def test_port_comes_from_the_single_source_of_truth(self):
        apps = {
            "svc-net-tor": {"services": {"tor": {"ports": {"local": {"socks": 9150}}}}}
        }
        self.assertEqual(resolve_proxy_url(apps), "socks5h://host.docker.internal:9150")

    def test_missing_port_raises(self):
        with self.assertRaises(AnsibleError):
            resolve_proxy_url({"svc-net-tor": {"services": {"tor": {}}}})


class _StubApplications:
    def run(self, terms, variables=None, roles_dir=None):
        return [APPS]


class TestTorSocksProxyLookup(unittest.TestCase):
    def test_terms_raise(self):
        lookup = LookupModule()
        lookup._templar = None
        with self.assertRaises(AnsibleError):
            lookup.run(["x"], variables={})

    def test_every_deployment_mode_gets_the_same_url(self):
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                lookup = LookupModule()
                lookup._templar = None
                lookup._loader = None
                with mock.patch.object(
                    lookup_loader, "get", return_value=_StubApplications()
                ):
                    self.assertEqual(
                        lookup.run([], variables={"DEPLOYMENT_MODE": mode})[0],
                        "socks5h://host.docker.internal:9050",
                    )


if __name__ == "__main__":
    unittest.main()
