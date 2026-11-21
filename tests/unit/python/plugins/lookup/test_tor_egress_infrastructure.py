from __future__ import annotations

import unittest

from plugins.lookup.tor_egress_infrastructure import (
    LookupModule,
    _registry_host,
    infrastructure,
    registries,
)
from utils.cache.yaml import load_yaml_any
from utils.networks.tor_egress import parse_entry
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT


def _apps(route: str = "onion", **extra) -> dict:
    return {
        "svc-net-tor": {
            "services": {
                "tor": {
                    "image": "debian",
                    "egress": {
                        "route": route,
                        "infrastructure": {
                            "mirrors": ["deb.debian.org"],
                            "ntp": ["pool.ntp.org"],
                            "registry_blob_hosts": {
                                "docker.io": ["production.cloudflare.docker.com"]
                            },
                            "acme": ["acme-v02.api.letsencrypt.org"],
                        },
                    },
                }
            }
        },
        **extra,
    }


class TestTorEgressInfrastructure(unittest.TestCase):
    def test_registries_come_from_the_deployed_images_only(self) -> None:
        apps = _apps(
            **{
                "web-app-x": {
                    "services": {
                        "x": {"image": "ghcr.io/acme/x"},
                        "y": {"image": "{{ dynamic }}"},
                    }
                },
                "web-app-y": {"services": {"y": {"image": "quay.io/acme/y"}}},
            }
        )
        self.assertEqual(
            registries(apps, ["svc-net-tor", "web-app-x"]), ["docker.io", "ghcr.io"]
        )

    def test_a_registry_port_is_stripped_and_local_registries_are_skipped(self) -> None:
        apps = _apps(
            **{
                "web-app-x": {
                    "services": {
                        "port": {"image": "registry.example.org:5000/acme/x"},
                        "local": {"image": "localhost:5000/acme/x"},
                        "sub": {"image": "cache.localhost/acme/x"},
                        "ipv4": {"image": "10.0.0.5:5000/acme/x"},
                        "ipv6": {"image": "[2001:db8::5]:5000/acme/x"},
                    }
                },
            }
        )
        found = registries(apps, ["web-app-x"])
        self.assertEqual(found, ["registry.example.org"])
        for entry in found:
            parse_entry(entry)

    def test_a_bracketed_ipv6_registry_is_no_host_name(self) -> None:
        """split_registry_and_name refuses a bracketed registry today, so
        registries() alone never reaches this branch of the host parser."""
        self.assertIsNone(_registry_host("[2001:db8::5]:5000"))
        self.assertIsNone(_registry_host("[2001:db8::5]"))
        self.assertEqual(
            _registry_host("Registry.Example.org:5000"), "registry.example.org"
        )

    def test_the_list_is_mirrors_ntp_registries_with_blob_hosts_then_acme(self) -> None:
        self.assertEqual(
            infrastructure(_apps(), ["svc-net-tor"]),
            [
                "deb.debian.org",
                "pool.ntp.org",
                "docker.io",
                "production.cloudflare.docker.com",
                "acme-v02.api.letsencrypt.org",
            ],
        )

    def test_none_pre_fills_nothing(self) -> None:
        self.assertEqual(infrastructure(_apps(route="none"), ["svc-net-tor"]), [])

    def test_off_a_tor_node_nothing_is_pre_filled(self) -> None:
        self.assertEqual(infrastructure(_apps(), ["web-app-x"]), [])
        self.assertEqual(
            LookupModule().run([], variables={"group_names": ["web-app-x"]}), [[]]
        )

    def test_an_incomplete_declaration_pre_fills_nothing_and_does_not_raise(
        self,
    ) -> None:
        apps = _apps()
        del apps["svc-net-tor"]["services"]["tor"]["egress"]["infrastructure"]["acme"]
        self.assertEqual(infrastructure(apps, ["svc-net-tor"]), [])
        apps["svc-net-tor"]["services"]["tor"]["egress"]["infrastructure"] = "mirrors"
        self.assertEqual(infrastructure(apps, ["svc-net-tor"]), [])

    def test_the_shipped_declaration_is_complete(self) -> None:
        services = load_yaml_any(
            str(PROJECT_ROOT / "roles/svc-net-tor" / ROLE_FILE_META_SERVICES)
        )
        entries = infrastructure(
            {"svc-net-tor": {"services": services}}, ["svc-net-tor"]
        )
        self.assertIn(
            "docker.io", entries, "the tor image itself is pulled from Docker Hub"
        )
        self.assertIn("acme-v02.api.letsencrypt.org", entries)
        self.assertIn("pool.ntp.org", entries)
        for entry in entries:
            with self.subTest(entry=entry):
                parse_entry(entry)


if __name__ == "__main__":
    unittest.main()
