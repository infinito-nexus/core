import unittest

from cli.administration.swarm.forget_node.command import inventory_hosts, main


class TestInventoryHosts(unittest.TestCase):
    def test_collects_group_and_meta_hosts(self):
        listing = {
            "_meta": {"hostvars": {"mgr-01": {}}},
            "all": {"children": ["svc-swarm-manager"]},
            "svc-swarm-manager": {"hosts": ["mgr-01", "mgr-02"]},
            "svc-db-redis": {"hosts": ["wrk-01"]},
        }
        self.assertEqual(inventory_hosts(listing), {"mgr-01", "mgr-02", "wrk-01"})


class TestMain(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def _run(self, cmd):
        self.calls.append(cmd)
        return 0

    def test_refuses_host_still_in_inventory(self):
        rc = main(
            ["inv.yml", "--host", "mgr-03"],
            load_hosts=lambda _inv: {"mgr-01", "mgr-02", "mgr-03"},
            run=self._run,
        )
        self.assertEqual(rc, 2)
        self.assertEqual(self.calls, [])

    def test_chains_into_swarm_deploy(self):
        rc = main(
            ["inv.yml", "--host", "mgr-03", "--password-file", "pw"],
            load_hosts=lambda _inv: {"mgr-01", "mgr-02", "mgr-04"},
            run=self._run,
        )
        self.assertEqual(rc, 0)
        (cmd,) = self.calls
        self.assertEqual(
            cmd[1:],
            [
                "-m",
                "cli.administration.deploy.swarm",
                "inv.yml",
                "--password-file",
                "pw",
                "-e",
                "SWARM_FORGET_NODE=mgr-03",
            ],
        )

    def test_propagates_deploy_failure(self):
        rc = main(
            ["inv.yml", "--host", "mgr-03"],
            load_hosts=lambda _inv: set(),
            run=lambda _cmd: 4,
        )
        self.assertEqual(rc, 4)


if __name__ == "__main__":
    unittest.main()
