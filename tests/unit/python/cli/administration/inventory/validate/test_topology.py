import shutil
import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.validate.topology import validate_swarm_topology
from utils.cache.yaml import dump_yaml


class TestValidateSwarmTopology(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir, True)

    def fresh_dir(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir, True)

    def write(self, groups, name="devices.yml"):
        content = {
            "all": {
                "children": {
                    group: {"hosts": dict.fromkeys(hosts)}
                    for group, hosts in groups.items()
                }
            }
        }
        dump_yaml(str(Path(self.test_dir) / name), content)

    def managers(self, count):
        self.fresh_dir()
        hosts = [f"m{i}" for i in range(count)]
        self.write({"svc-swarm-manager": hosts, "svc-swarm-node": hosts})
        return validate_swarm_topology(self.test_dir)

    def test_valid_manager_counts(self):
        for count in (0, 1, 3, 5):
            with self.subTest(count=count):
                self.assertEqual(self.managers(count), [])

    def test_even_manager_counts_fail(self):
        for count in (2, 4):
            with self.subTest(count=count):
                errors = self.managers(count)
                self.assertEqual(len(errors), 1)
                self.assertIn("svc-swarm-manager", errors[0])
                self.assertIn(str(count), errors[0])

    def test_nodes_without_manager_fail(self):
        self.write({"svc-swarm-node": ["n1", "n2"]})
        errors = validate_swarm_topology(self.test_dir)
        self.assertEqual(len(errors), 1)
        self.assertIn("svc-swarm-manager", errors[0])

    def test_hosts_merge_across_files(self):
        self.write({"svc-swarm-manager": ["m0", "m1"]}, "a.yml")
        self.write({"svc-swarm-manager": ["m2"]}, "b.yml")
        self.assertEqual(validate_swarm_topology(self.test_dir), [])

    def test_engine_host_outside_swarm_node_fails(self):
        self.write(
            {
                "svc-swarm-manager": ["m0", "m1", "m2"],
                "svc-swarm-node": ["m0", "m1", "m2"],
                "svc-db-postgres": ["m0", "m1", "outsider"],
            }
        )
        errors = validate_swarm_topology(self.test_dir)
        self.assertEqual(len(errors), 1)
        self.assertIn("outsider", errors[0])
        self.assertIn("svc-db-postgres", errors[0])

    def etcd(self, count):
        self.fresh_dir()
        hosts = [f"m{i}" for i in range(5)]
        self.write(
            {
                "svc-swarm-manager": hosts,
                "svc-swarm-node": hosts,
                "svc-dcs-etcd": hosts[:count],
            }
        )
        return validate_swarm_topology(self.test_dir)

    def test_valid_etcd_member_counts(self):
        for count in (0, 1, 3, 5):
            with self.subTest(count=count):
                self.assertEqual(self.etcd(count), [])

    def test_even_etcd_member_counts_fail(self):
        for count in (2, 4):
            with self.subTest(count=count):
                errors = self.etcd(count)
                self.assertEqual(len(errors), 1)
                self.assertIn("svc-dcs-etcd", errors[0])
                self.assertIn(str(count), errors[0])

    def test_engine_group_ignored_without_swarm(self):
        self.write({"svc-db-postgres": ["h1", "h2"]})
        self.assertEqual(validate_swarm_topology(self.test_dir), [])


if __name__ == "__main__":
    unittest.main()
