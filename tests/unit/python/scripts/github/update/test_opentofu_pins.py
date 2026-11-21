from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "cron-update.yml"
SHIM = PROJECT_ROOT / "scripts" / "github" / "update" / "opentofu_pins.sh"


class TestWorkflow(unittest.TestCase):
    def test_the_update_workflow_runs_the_opentofu_updater(self):
        job = load_yaml_str(read_text(str(WORKFLOW)))["jobs"]["update-opentofu-pins"]
        self.assertEqual(job["if"], "vars.CI_ENABLE_AUTO_UPDATES == 'true'")
        runs = [step.get("run", "") for step in job["steps"]]
        self.assertIn("bash scripts/github/update/opentofu_pins.sh", runs)
        self.assertEqual(runs[-1], "bash scripts/github/update/open/role_prs.sh roles")
        self.assertLess(
            runs.index("bash scripts/github/update/opentofu_pins.sh"), len(runs) - 1
        )
        self.assertIn(
            'python3 -m cli.contributing.update.opentofu "$@"', read_text(str(SHIM))
        )


if __name__ == "__main__":
    unittest.main()
