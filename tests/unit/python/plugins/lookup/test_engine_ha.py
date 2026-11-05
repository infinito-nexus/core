from __future__ import annotations

import importlib
import unittest
from unittest import mock

from ansible.errors import AnsibleError

plugin_module = importlib.import_module("plugins.lookup.engine")

NODES = ["m1", "m2", "m3"]


def _applications(shared: bool) -> dict:
    return {
        "web-app-foo": {"services": {"redis": {"enabled": True, "shared": shared}}},
        "svc-db-redis": {
            "services": {"redis": {"name": "redis-central"}},
            "secrets": {"credentials": {"REDIS_PASSWORD": "pw"}},
        },
    }


class TestEngineLookupHa(unittest.TestCase):
    def _run(self, shared=True, hosts=NODES, mode="swarm", want="all"):
        apps = _applications(shared)
        vars_ = {
            "applications": apps,
            "DEPLOYMENT_MODE": mode,
            "BIN_RESOLVE_DB_PRIMARY": "/usr/bin/resolve-db-primary",
            "groups": {"svc-db-redis": list(hosts), "svc-swarm-node": NODES},
        }
        lookup = plugin_module.LookupModule()
        lookup._templar = None
        lookup._loader = mock.MagicMock()
        entity = mock.patch.object(
            plugin_module,
            "entity_name",
            side_effect=lambda role: role.rsplit("-", 1)[-1],
        )
        loader = mock.patch.object(plugin_module, "lookup_loader")
        with entity, loader as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda _t, variables=None, **_k: [apps]
            )
            return lookup.run(["redis", "web-app-foo", want], variables=vars_)[0]

    def test_ha_host_keeps_the_endpoint_name(self):
        self.assertEqual(self._run(want="host"), "redis-central")

    def test_ha_address_resolves_the_primary_at_call_time(self):
        self.assertEqual(
            self._run(want="address"),
            '"$(/usr/bin/resolve-db-primary redis redis)"',
        )

    def test_ha_container_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(want="container")

    def test_single_host_keeps_the_standalone_container(self):
        self.assertEqual(self._run(hosts=["m1"], want="container"), "redis-central")

    def test_single_host_swarm_address_resolves_the_service(self):
        self.assertEqual(
            self._run(hosts=["m1"], want="address"),
            '"$(/usr/bin/resolve-container-id redis redis)"',
        )

    def test_compose_address_is_the_container_name(self):
        self.assertEqual(self._run(mode="compose", want="address"), "redis-central")

    def test_compose_mode_keeps_the_standalone_container(self):
        self.assertEqual(self._run(mode="compose", want="container"), "redis-central")

    def test_standalone_dict_is_unchanged_by_the_ha_arm(self):
        swarm = self._run(hosts=["m1"])
        compose = self._run(mode="compose")
        swarm.pop("address")
        compose.pop("address")
        self.assertEqual(swarm, compose)

    def test_embedded_sidecar_is_never_ha(self):
        self.assertEqual(self._run(shared=False, want="container"), "foo-redis")


if __name__ == "__main__":
    unittest.main()
