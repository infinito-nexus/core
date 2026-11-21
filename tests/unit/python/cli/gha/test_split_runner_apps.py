from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "github" / "split_runner_apps.sh"


def _fresh_step_env(**values: str) -> dict[str, str]:
    """The environment of a new CI step: nothing the env loader exported.

    Args:
        values: keys the step sets itself, as a workflow ``env:`` would.

    Returns:
        The process environment without ``INFINITO_*`` keys, plus *values*.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("INFINITO_")}
    env.update(values)
    return env


def _run(apps: list, self_hosted_count: int, env: dict[str, str] | None = None) -> dict:
    with tempfile.NamedTemporaryFile(mode="r", suffix=".env", delete=False) as out_f:
        out_path = out_f.name
    try:
        env = os.environ.copy() if env is None else dict(env)
        env["APPS_JSON"] = json.dumps(apps)
        env["CI_SELF_HOSTED_RUNNER_COUNT"] = str(self_hosted_count)
        env["GITHUB_OUTPUT"] = out_path
        subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True)
        result = {}
        for line in Path(out_path).read_text().splitlines():  # nocheck: cache-read
            key, _, value = line.partition("=")
            result[key] = json.loads(value)
        return result
    finally:
        Path(out_path).unlink(missing_ok=True)


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

    def test_an_empty_concurrency_splits_like_an_unset_one(self):
        apps = list(range(40))
        self.assertEqual(
            _run(apps, 20, _fresh_step_env(INFINITO_CI_CONCURRENCY="")),
            _run(apps, 20, _fresh_step_env()),
        )

    def test_a_set_concurrency_drives_the_split(self):
        out = _run(list(range(40)), 20, _fresh_step_env(INFINITO_CI_CONCURRENCY="500"))
        self.assertEqual(len(out["apps_github"]), 40 * 500 // (500 + 20))


if __name__ == "__main__":
    unittest.main()
