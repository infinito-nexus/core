from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from utils.failover import inventory as inv

_VARS = {"ansible_connection": "docker"}


def _inventory() -> dict:
    return {
        "all": {
            "children": {
                "svc-swarm-node": {
                    "hosts": {h: dict(_VARS) for h in ("m1", "m2", "m3", "w1")}
                },
                "svc-swarm-manager": {
                    "hosts": {h: dict(_VARS) for h in ("m1", "m2", "m3")}
                },
                "svc-db-postgres": {
                    "hosts": {h: dict(_VARS) for h in ("m1", "m2", "m3")}
                },
            }
        }
    }


_HOST_VARS = """\
applications:
  svc-db-postgres:
    secrets:
      credentials:
        POSTGRES_PASSWORD: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          6131
    services:
      postgres:
        mem_limit: 768m
        mem_reservation: 768m
"""


class TestGroups(unittest.TestCase):
    def test_replace_host_keeps_position_and_stack_host_first(self):
        out = inv.replace_host(_inventory(), "m2", "w1")
        self.assertEqual(inv.group_hosts(out, "svc-swarm-manager"), ["m1", "w1", "m3"])
        self.assertEqual(inv.group_hosts(out, "svc-db-postgres"), ["m1", "w1", "m3"])
        self.assertEqual(inv.group_hosts(out, "svc-swarm-node"), ["m1", "w1", "m3"])
        self.assertEqual(
            inv.group_hosts(_inventory(), "svc-swarm-manager"), ["m1", "m2", "m3"]
        )

    def test_set_group_hosts_reuses_known_host_vars(self):
        out = inv.set_group_hosts(_inventory(), "svc-db-postgres", ["m1"])
        self.assertEqual(inv.group_hosts(out, "svc-db-postgres"), ["m1"])
        self.assertEqual(
            out["all"]["children"]["svc-db-postgres"]["hosts"]["m1"], _VARS
        )
        with self.assertRaises(ValueError):
            inv.set_group_hosts(_inventory(), "svc-db-postgres", ["ghost"])


class TestMemory(unittest.TestCase):
    def test_memory_sizes(self):
        self.assertEqual(inv.memory_mb("768m"), 768)
        self.assertEqual(inv.memory_mb("1g"), 1024)
        with self.assertRaises(ValueError):
            inv.memory_mb("lots")

    def test_bump_raises_limit_and_reservation(self):
        data = {
            "applications": {
                "a": {
                    "services": {"s": {"mem_limit": "768m", "mem_reservation": "512m"}}
                }
            }
        }
        out = inv.bump_memory(data, app_id="a", service="s", delta_mb=32)
        self.assertEqual(
            out["applications"]["a"]["services"]["s"],
            {"mem_limit": "800m", "mem_reservation": "544m"},
        )
        self.assertEqual(
            data["applications"]["a"]["services"]["s"]["mem_limit"], "768m"
        )

    def test_lab_inventory_bump_keeps_vaulted_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "host_vars").mkdir()
            (root / "host_vars" / "m1.yml").write_text(_HOST_VARS)
            (root / "host_vars" / "nfs.yml").write_text("applications: {}\n")
            (root / "devices.yml").write_text("all: {}\n")
            lab = inv.LabInventory(root / "devices.yml")
            self.assertEqual(
                lab.bump_memory(
                    app_id="svc-db-postgres", service="postgres", delta_mb=32
                ),
                1,
            )
            text = (
                root / "host_vars" / "m1.yml"
            ).read_text()  # nocheck: cache-read — re-reads the file just written
        self.assertIn("!vault |", text)
        self.assertIn("$ANSIBLE_VAULT;1.1;AES256", text)
        self.assertIn("mem_limit: 800m", text)


class TestFindInventory(unittest.TestCase):
    def test_newest_round_dir_wins(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "inv"
            for name in ("inv-0", "inv-1"):
                (Path(td) / name).mkdir()
                (Path(td) / name / "devices.yml").write_text("all: {}\n")
            older = time.time() - 100
            os.utime(Path(td) / "inv-0" / "devices.yml", (older, older))
            self.assertEqual(inv.find_inventory(str(base)).parent.name, "inv-1")
            with self.assertRaises(RuntimeError):
                inv.find_inventory(str(Path(td) / "other"))


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.lab = inv.LabInventory(Path("/x/inv-0/devices.yml"))

    def test_deploy_mirrors_the_matrix_options(self):
        argv = inv.deploy_argv(self.lab, "py")
        self.assertEqual(
            argv[:4],
            ["py", "-m", "cli.administration.deploy.swarm", "/x/inv-0/devices.yml"],
        )
        self.assertIn("--skip-build", argv)
        self.assertIn("@/x/inv-0/swarm-nfs-extras.deploy.yml", argv)
        self.assertIn(f"@/x/inv-0/{inv.SUITE_EXTRAS}", argv)

    def test_forget_goes_through_the_make_target(self):
        argv = inv.forget_argv(self.lab, "m2")
        self.assertEqual(
            argv[:3], ["make", "--no-print-directory", "swarm-forget-node"]
        )
        self.assertIn("host=m2", argv)
        self.assertIn("inventory=/x/inv-0/devices.yml", argv)
        self.assertTrue(argv[-1].startswith("args=-p /x/inv-0/.password"))

    def test_playbook_passes_vars_as_one_json(self):
        argv = inv.playbook_argv(self.lab, "etcd-operation.yml", {"op": "move-leader"})
        self.assertEqual(json.loads(argv[argv.index("-e") + 1]), {"op": "move-leader"})
        self.assertTrue(argv[-1].endswith("playbooks/etcd-operation.yml"))
        self.assertNotIn("--limit", argv)

    def test_playbook_limit_targets_one_host_pattern(self):
        argv = inv.playbook_argv(self.lab, "etcd-operation.yml", {}, limit="mgr-02")
        self.assertEqual(argv[argv.index("--limit") + 1], "mgr-02")
        self.assertTrue(argv[-1].endswith("etcd-operation.yml"))


if __name__ == "__main__":
    unittest.main()
