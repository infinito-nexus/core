from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[4] / "scripts" / "github" / "split_runner_apps.sh"
)


def _run(apps: list, self_hosted_count: int) -> dict:
    with tempfile.NamedTemporaryFile(mode="r", suffix=".env", delete=False) as out_f:
        out_path = out_f.name
    try:
        env = os.environ.copy()
        env["APPS_JSON"] = json.dumps(apps)
        env["CI_SELF_HOSTED_RUNNER_COUNT"] = str(self_hosted_count)
        env["GITHUB_OUTPUT"] = out_path
        subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True)
        result = {}
        for line in Path(out_path).read_text().splitlines():
            key, _, value = line.partition("=")
            result[key] = json.loads(value)
        return result
    finally:
        os.unlink(out_path)


class TestSplitRunnerApps(unittest.TestCase):
    def test_all_to_github_when_self_hosted_disabled(self):
        apps = ["a", "b", "c"]
        out = _run(apps, 0)
        self.assertEqual(out["apps_github"], apps)
        self.assertEqual(out["apps_self_hosted"], [])

    def test_all_to_github_when_empty_list(self):
        out = _run([], 5)
        self.assertEqual(out["apps_github"], [])
        self.assertEqual(out["apps_self_hosted"], [])

    def test_split_proportionally(self):
        # 20 github quota + 20 self-hosted → 50/50 split
        apps = list(range(40))
        out = _run(apps, 20)
        self.assertEqual(len(out["apps_github"]) + len(out["apps_self_hosted"]), 40)
        self.assertGreater(len(out["apps_github"]), 0)
        self.assertGreater(len(out["apps_self_hosted"]), 0)

    def test_no_apps_lost_in_split(self):
        apps = [f"app-{i}" for i in range(30)]
        out = _run(apps, 10)
        combined = out["apps_github"] + out["apps_self_hosted"]
        self.assertEqual(sorted(combined), sorted(apps))

    def test_single_app_goes_to_github(self):
        out = _run(["only-app"], 5)
        combined = out["apps_github"] + out["apps_self_hosted"]
        self.assertEqual(combined, ["only-app"])


if __name__ == "__main__":
    unittest.main()
