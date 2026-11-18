import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

HANDLERS = PROJECT_ROOT / "roles" / "sys-svc-compose" / "handlers" / "swarm.yml"
ROLLING = "roles/sys-svc-compose/tasks/utils/swarm/db_ha_rolling.yml"
GUARD = "roles/sys-svc-compose/tasks/utils/swarm/db_ha_drift_guard.yml"


class TestSwarmDriftGuardRunsAfterTheDeploy(unittest.TestCase):
    def setUp(self):
        self.handlers = load_yaml_any(str(HANDLERS))

    def index_of(self, predicate):
        matches = [
            index for index, handler in enumerate(self.handlers) if predicate(handler)
        ]
        self.assertEqual(len(matches), 1, matches)
        return matches[0]

    def includes(self, path):
        return self.index_of(
            lambda h: path in str(h.get("ansible.builtin.include_tasks", ""))
        )

    def test_the_guard_follows_the_roll_the_deploy_and_the_convergence(self):
        deploy = self.index_of(
            lambda h: "docker stack deploy" in str(h.get("ansible.builtin.shell", ""))
        )
        converge = self.index_of(
            lambda h: "stack_ready.sh" in str(h.get("ansible.builtin.script", ""))
        )
        guard = self.includes(GUARD)
        self.assertLess(self.includes(ROLLING), deploy)
        self.assertLess(deploy, converge)
        self.assertLess(converge, guard)

    def test_the_guard_listens_wherever_the_roll_listens(self):
        self.assertEqual(
            set(self.handlers[self.includes(GUARD)]["listen"]),
            set(self.handlers[self.includes(ROLLING)]["listen"]),
        )
        self.assertEqual(
            self.handlers[self.includes(GUARD)]["when"],
            self.handlers[self.includes(ROLLING)]["when"],
        )


if __name__ == "__main__":
    unittest.main()
