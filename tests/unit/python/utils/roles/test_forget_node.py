import unittest

from utils.roles.forget_node import ForgetNodeError, forget_node_plan


class TestForgetNodePlan(unittest.TestCase):
    def test_refuses_ready_node(self):
        with self.assertRaisesRegex(ForgetNodeError, "not 'down'"):
            forget_node_plan("mgr-03", "ready manager")

    def test_refuses_unknown_state(self):
        with self.assertRaisesRegex(ForgetNodeError, "not 'down'"):
            forget_node_plan("mgr-03", "unknown worker")

    def test_refuses_node_swarm_does_not_know(self):
        with self.assertRaisesRegex(ForgetNodeError, "does not report"):
            forget_node_plan("mgr-03", "")

    def test_down_manager(self):
        self.assertEqual(
            forget_node_plan("Mgr_03", "down manager\n"),
            {
                "node": "Mgr_03",
                "host_id": "mgr-03",
                "manager": True,
                "etcd_member": "etcd-mgr-03",
            },
        )

    def test_down_worker(self):
        self.assertFalse(forget_node_plan("wrk-01", "down worker")["manager"])


if __name__ == "__main__":
    unittest.main()
