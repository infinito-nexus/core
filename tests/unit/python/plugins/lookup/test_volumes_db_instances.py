from __future__ import annotations

import os
import unittest

from plugins.lookup.compose_volumes import compose_volumes
from plugins.lookup.container_volumes import container_volumes
from utils.cache.yaml import load_yaml_str

_DIR_VAR_LIB = os.environ["INFINITO_DIR_VAR_LIB"]

META = {
    "data": {
        "type": "volume",
        "name": "openldap_data",
        "mounts": [{"service": "openldap", "target": "/var/lib/ldap"}],
    },
    "ldif": {
        "type": "bind",
        "source": "/srv/ldif",
        "mounts": [{"service": "openldap", "target": "/ldif"}],
    },
}

INSTANCES = [
    {"host": "m1", "host_id": "m1", "service": "openldap-m1", "legacy": True},
    {"host": "m2", "host_id": "m2", "service": "openldap-m2", "legacy": False},
]


def _apps():
    return {"svc-db-fakeengine": {"volumes": META, "services": {}}}


class TestContainerVolumesInstance(unittest.TestCase):
    def render(self, instance):
        out = container_volumes(
            _apps(), "svc-db-fakeengine", "openldap", instance=instance
        )
        return load_yaml_str(out)["volumes"]

    def test_without_instance_unchanged(self):
        self.assertEqual(self.render(None), ["data:/var/lib/ldap", "/srv/ldif:/ldif"])

    def test_instance_suffixes_named_volumes_only(self):
        self.assertEqual(
            self.render(INSTANCES[1]), ["data_m2:/var/lib/ldap", "/srv/ldif:/ldif"]
        )

    def test_legacy_instance_also_gets_own_key(self):
        self.assertEqual(self.render(INSTANCES[0])[0], "data_m1:/var/lib/ldap")


class TestComposeVolumesInstances(unittest.TestCase):
    def render(self, instances):
        out = compose_volumes(
            _apps(),
            "svc-db-fakeengine",
            deployment_mode="swarm",
            storage={"backend": "nfs"},
            dir_var_lib=_DIR_VAR_LIB,
            instances=instances,
        )
        return load_yaml_str(out)["volumes"]

    def test_without_instances_unchanged(self):
        volumes = self.render(None)
        self.assertIn("data", volumes)
        self.assertEqual(volumes["data"]["name"], "openldap_data")

    def test_instances_expand_named_volumes_as_local(self):
        volumes = self.render(INSTANCES)
        self.assertNotIn("data", volumes)
        self.assertEqual(volumes["data_m1"], {"name": "openldap_data"})
        self.assertEqual(volumes["data_m2"], {"name": "openldap_data_m2"})


if __name__ == "__main__":
    unittest.main()
