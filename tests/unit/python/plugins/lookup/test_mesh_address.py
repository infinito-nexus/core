from __future__ import annotations

import unittest

from ansible.errors import AnsibleError

import plugins.lookup.mesh_address as module


def _hostvars(host: str, *interfaces: dict) -> dict:
    return {
        host: {
            "applications": {
                "svc-net-wireguard": {"networks": {"interfaces": list(interfaces)}}
            }
        }
    }


def _run(host: str, hostvars: dict) -> str:
    return module.LookupModule().run([host], variables={"hostvars": hostvars})[0]


class TestMeshAddress(unittest.TestCase):
    def test_the_primary_interface_is_returned(self):
        hostvars = _hostvars(
            "nfs",
            {
                "name": "gamma",
                "host": "nfs",
                "address": "10.100.12.11",
                "primary": False,
            },
            {"name": "beta", "host": "nfs", "address": "10.100.11.11", "primary": True},
        )
        self.assertEqual("10.100.11.11", _run("nfs", hostvars))

    def test_an_entry_another_host_owns_is_ignored(self):
        hostvars = _hostvars(
            "wrk",
            {"name": "swarm", "host": "mgr", "address": "10.100.0.1", "primary": True},
        )
        self.assertEqual("", _run("wrk", hostvars))

    def test_a_host_off_the_mesh_has_no_address(self):
        self.assertEqual("", _run("wrk", {"wrk": {}}))
        self.assertEqual("", _run("absent", {}))

    def test_a_peer_is_found_in_the_hosts_own_interfaces(self):
        hostvars = _hostvars(
            "galaxyserver",
            {
                "name": "alpha",
                "host": "galaxyserver",
                "address": "10.100.0.2",
                "primary": True,
                "peers": [
                    {"host": "echoserver", "address": "10.100.0.1", "is_hub": True}
                ],
            },
        )
        found = module.LookupModule().run(
            ["galaxyserver"], variables={"hostvars": hostvars}, peer="echoserver"
        )
        self.assertEqual(["10.100.0.1"], found)

    def test_a_peer_the_host_does_not_list_has_no_address(self):
        hostvars = _hostvars(
            "galaxyserver",
            {
                "name": "alpha",
                "host": "galaxyserver",
                "address": "10.100.0.2",
                "primary": True,
                "peers": [
                    {"host": "echoserver", "address": "10.100.0.1", "is_hub": True}
                ],
            },
        )
        found = module.LookupModule().run(
            ["galaxyserver"], variables={"hostvars": hostvars}, peer="hotelserver"
        )
        self.assertEqual([""], found)

    def test_the_primary_interface_answers_before_another_mesh(self):
        hostvars = _hostvars(
            "galaxyserver",
            {
                "name": "beta",
                "host": "galaxyserver",
                "address": "10.100.11.2",
                "primary": False,
                "peers": [{"host": "echoserver", "address": "10.100.11.1"}],
            },
            {
                "name": "alpha",
                "host": "galaxyserver",
                "address": "10.100.0.2",
                "primary": True,
                "peers": [{"host": "echoserver", "address": "10.100.0.1"}],
            },
        )
        found = module.LookupModule().run(
            ["galaxyserver"], variables={"hostvars": hostvars}, peer="echoserver"
        )
        self.assertEqual(["10.100.0.1"], found)

    def test_exactly_one_hostname_is_required(self):
        for terms in ([], ["a", "b"]):
            with self.subTest(terms=terms), self.assertRaises(AnsibleError):
                module.LookupModule().run(terms, variables={})


if __name__ == "__main__":
    unittest.main()
