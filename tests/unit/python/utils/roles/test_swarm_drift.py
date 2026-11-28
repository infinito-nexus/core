import json
import unittest

from plugins.filter.swarm.drifted_members import swarm_drifted_members
from utils.roles.swarm_drift import SwarmDriftError, drift_report, drifted_fields

STACK = "postgres"
MEMBER = "postgres-m1"
CONFIG = {
    "secrets": {"patroni_cfg": {"name": "postgres_patroni_cfg_71c49f6f"}},
    "configs": {},
    "services": {
        MEMBER: {
            "image": "m1:5000/postgres_custom:18",
            "entrypoint": ["patroni-entrypoint.sh"],
            "command": ["/run/secrets/patroni.yml", "/var/run/postgresql/patroni.yml"],
            "environment": {"PATRONI_NAME": "postgres-m1", "TZ": "UTC"},
            "deploy": {
                "resources": {
                    "limits": {"cpus": "2.0", "memory": "838860800", "pids": 1024},
                    "reservations": {"memory": "838860800"},
                },
                "placement": {"constraints": ["node.labels.infinito.host_id == m1"]},
            },
            "secrets": [
                {"source": "patroni_cfg", "target": "patroni.yml", "mode": 288}
            ],
            "volumes": [
                {
                    "type": "bind",
                    "source": "/etc/infinito.nexus/ca/root-ca.crt",
                    "target": "/tmp/infinito/ca/root-ca.crt",
                    "read_only": True,
                },
                {
                    "type": "volume",
                    "source": "data_m1",
                    "target": "/var/lib/postgresql",
                },
            ],
        }
    },
}


def running_spec(**overrides):
    container = {
        "Image": "m1:5000/postgres_custom:18@sha256:" + "a" * 64,
        "Command": ["patroni-entrypoint.sh"],
        "Args": ["/run/secrets/patroni.yml", "/var/run/postgresql/patroni.yml"],
        "Env": ["PATRONI_NAME=postgres-m1", "TZ=UTC"],
        "Secrets": [
            {
                "SecretName": "postgres_patroni_cfg_71c49f6f",
                "File": {"Name": "/run/secrets/patroni.yml"},
            }
        ],
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/etc/infinito.nexus/ca/root-ca.crt",
                "Target": "/tmp/infinito/ca/root-ca.crt",
                "ReadOnly": True,
            },
            {
                "Type": "volume",
                "Source": "postgres_data",
                "Target": "/var/lib/postgresql",
            },
        ],
    }
    container.update(overrides.pop("container", {}))
    task = {
        "ContainerSpec": container,
        "Resources": {
            "Limits": {
                "NanoCPUs": 2_000_000_000,
                "MemoryBytes": 838860800,
                "Pids": 1024,
            },
            "Reservations": {"MemoryBytes": 838860800},
        },
        "Placement": {"Constraints": ["node.labels.infinito.host_id == m1"]},
    }
    task.update(overrides)
    return {"TaskTemplate": task}


def drift(spec):
    return drifted_fields(CONFIG["services"][MEMBER], CONFIG, STACK, spec)


class TestDriftedFields(unittest.TestCase):
    def test_an_unchanged_member_has_no_drift(self):
        self.assertEqual(drift(running_spec()), [])

    def test_a_memory_bump_is_a_resource_drift(self):
        spec = running_spec(
            Resources={
                "Limits": {
                    "NanoCPUs": 2_000_000_000,
                    "MemoryBytes": 805306368,
                    "Pids": 1024,
                },
                "Reservations": {"MemoryBytes": 838860800},
            }
        )
        self.assertEqual(drift(spec), ["resources"])

    def test_a_rotated_secret_is_a_drift(self):
        spec = running_spec(
            container={
                "Secrets": [
                    {
                        "SecretName": "postgres_patroni_cfg_00000000",
                        "File": {"Name": "/run/secrets/patroni.yml"},
                    }
                ]
            }
        )
        self.assertEqual(drift(spec), ["secrets"])

    def test_a_new_image_and_an_env_change_are_drifts(self):
        spec = running_spec(
            container={"Image": "m1:5000/postgres_custom:17", "Env": ["TZ=UTC"]}
        )
        self.assertEqual(drift(spec), ["env", "image"])

    def test_the_report_names_env_keys_but_no_values(self):
        spec = running_spec(
            container={
                "Image": "m1:5000/postgres_custom:17",
                "Env": ["TZ=Europe/Berlin", "PATRONI_NAME=postgres-m1"],
            }
        )
        report = drift_report(CONFIG["services"][MEMBER], CONFIG, STACK, spec)
        self.assertEqual(report, ["env:TZ", "image"])
        self.assertNotIn("UTC", " ".join(report))

    def test_human_sizes_are_read(self):
        service = json.loads(json.dumps(CONFIG["services"][MEMBER]))
        service["deploy"]["resources"]["limits"]["memory"] = "800M"
        service["deploy"]["resources"]["reservations"]["memory"] = "800MiB"
        self.assertEqual(drifted_fields(service, CONFIG, STACK, running_spec()), [])

    def test_an_unreadable_size_raises(self):
        service = json.loads(json.dumps(CONFIG["services"][MEMBER]))
        service["deploy"]["resources"]["limits"]["memory"] = "lots"
        with self.assertRaises(SwarmDriftError):
            drifted_fields(service, CONFIG, STACK, running_spec())


class TestDriftedMembersFilter(unittest.TestCase):
    def test_only_drifted_running_members_are_named(self):
        bumped = running_spec(
            Resources={
                "Limits": {
                    "NanoCPUs": 1_000_000_000,
                    "MemoryBytes": 838860800,
                    "Pids": 1024,
                },
                "Reservations": {"MemoryBytes": 838860800},
            }
        )
        config = json.loads(json.dumps(CONFIG))
        config["services"]["postgres-m2"] = config["services"][MEMBER]
        config["services"]["postgres-m3"] = config["services"][MEMBER]
        results = [
            {"item": MEMBER, "rc": 0, "stdout": json.dumps(running_spec())},
            {"item": "postgres-m2", "rc": 0, "stdout": json.dumps(bumped)},
            {"item": "postgres-m3", "rc": 1, "stdout": ""},
        ]
        self.assertEqual(
            swarm_drifted_members(json.dumps(config), STACK, results),
            ["postgres-m2"],
        )


if __name__ == "__main__":
    unittest.main()
