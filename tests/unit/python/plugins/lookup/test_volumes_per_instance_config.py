from __future__ import annotations

import os
import unittest

from plugins.lookup.compose_volumes import compose_volumes
from plugins.lookup.container_volumes import container_volumes
from utils.cache.yaml import load_yaml_str

_DIR_VAR_LIB = os.environ["INFINITO_DIR_VAR_LIB"]

META = {
    "cn_config": {
        "type": "config",
        "per_instance": True,
        "source": "/srv/cn-config/{host_id}.ldif",
        "mode": "0444",
        "mounts": [{"service": "openldap", "target": "/etc/ldap/cn-config.ldif"}],
    },
}

INSTANCES = [
    {"host": "m1", "host_id": "m1", "service": "openldap-m1", "legacy": True},
    {"host": "m2", "host_id": "m2", "service": "openldap-m2", "legacy": False},
]


def _apps():
    return {"svc-db-fakeengine": {"volumes": META, "services": {}}}


class TestPerInstanceConfig(unittest.TestCase):
    def test_compose_declares_one_config_per_instance(self):
        out = compose_volumes(
            _apps(),
            "svc-db-fakeengine",
            deployment_mode="swarm",
            dir_var_lib=_DIR_VAR_LIB,
            instances=INSTANCES,
        )
        configs = load_yaml_str(out)["configs"]
        self.assertEqual(set(configs), {"cn_config_m1", "cn_config_m2"})
        self.assertEqual(configs["cn_config_m2"]["file"], "/srv/cn-config/m2.ldif")
        self.assertNotEqual(
            configs["cn_config_m1"]["name"], configs["cn_config_m2"]["name"]
        )

    def test_standalone_declares_none(self):
        out = compose_volumes(
            _apps(),
            "svc-db-fakeengine",
            deployment_mode="swarm",
            dir_var_lib=_DIR_VAR_LIB,
        )
        self.assertNotIn("configs", load_yaml_str(out))

    def test_instance_mounts_its_own_config(self):
        out = container_volumes(
            _apps(), "svc-db-fakeengine", "openldap", instance=INSTANCES[1]
        )
        self.assertEqual(
            load_yaml_str(out)["configs"],
            [
                {
                    "source": "cn_config_m2",
                    "target": "/etc/ldap/cn-config.ldif",
                    "mode": 0o444,
                }
            ],
        )

    def test_standalone_service_mounts_nothing(self):
        self.assertEqual(
            container_volumes(_apps(), "svc-db-fakeengine", "openldap"), ""
        )


if __name__ == "__main__":
    unittest.main()
