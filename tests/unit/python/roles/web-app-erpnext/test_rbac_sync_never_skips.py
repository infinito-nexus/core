from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles" / "web-app-erpnext"
SYNC_TASKS = ROLE / "tasks" / "04_rbac.yml"


class TestTheRbacSyncNeverSkipsErpnext(unittest.TestCase):
    def test_the_hook_runs_on_every_timer_run(self) -> None:
        [task] = load_yaml_any(str(SYNC_TASKS))
        self.assertIs(task["vars"]["rbac_sync_skip_unchanged"], False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
