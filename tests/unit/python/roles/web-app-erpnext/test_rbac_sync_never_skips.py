from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles" / "web-app-erpnext"
SYNC_TASKS = ROLE / "tasks" / "04_rbac.yml"
SIGN_IN = ROLE / "files" / "python" / "infinito_rbac" / "infinito_rbac" / "login.py"


class TestTheRbacSyncNeverSkipsErpnext(unittest.TestCase):
    def test_the_sign_in_converge_grants_roles_outside_the_sync(self) -> None:
        source = read_text(str(SIGN_IN))
        self.assertIn("user.add_roles(", source)
        self.assertIn("converge_mapped(user, wanted_mapped)", source)

    def test_the_hook_runs_on_every_timer_run(self) -> None:
        [task] = load_yaml_any(str(SYNC_TASKS))
        self.assertIs(task["vars"]["rbac_sync_skip_unchanged"], False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
