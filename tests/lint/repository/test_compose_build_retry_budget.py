"""Contract of the retried image builds in the sys-svc-compose handlers.

Both build tasks retry a transient network fault instead of immediately
rebuilding without cache, and fall back to a cache-discarding rebuild only once
the spaced retries are exhausted. Two properties keep that safe and are pinned
here: the worst-case wall clock of the ladder plus its fallback must stay under
the per-distro sweep budget and the deploy step cap, and the fallback must exist
- the ladder carries ``ignore_errors``, so removing the fallback would turn a
failed build into a silent pass. The registry pre-pull is gated on the sync task
being skipped rather than on a second copy of the excluded application id.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.env.parser import parse_static_env

from . import PROJECT_ROOT

HANDLERS = PROJECT_ROOT / "roles" / "sys-svc-compose" / "handlers"
SWARM = HANDLERS / "swarm.yml"
COMPOSE = HANDLERS / "compose.yml"
COMPOSE_WORKFLOW = (
    PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy-compose.yml"
)

BUILDS = {
    "swarm: pre-deploy build of local images": (SWARM, "_swarm_pre_deploy_build"),
    "Build compose": (COMPOSE, "compose_build"),
}
TIMEOUT_LOOKUP = re.compile(r"lookup\('timeout',\s*(\d+)\s*\)")


def _tasks(path):
    return load_yaml_any(str(path), default_if_missing=[]) or []


def _timeout(task):
    return int(TIMEOUT_LOOKUP.search(str(task["timeout"])).group(1))


def _fallbacks(path, var):
    return [
        t
        for t in _tasks(path)
        if t.get("when") == f"{var} is failed"
        and "--no-cache" in t.get("ansible.builtin.shell", "")
    ]


def _longest_step_seconds(path):
    document = load_yaml_any(str(path), default_if_missing={}) or {}
    return 60 * max(
        step["timeout-minutes"]
        for job in (document.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if "timeout-minutes" in step
    )


def _by_name(path, name):
    return next((t for t in _tasks(path) if t.get("name") == name), None)


class TestComposeBuildRetryBudget(unittest.TestCase):
    def test_the_ladder_body_does_not_discard_the_cache(self) -> None:
        for name, (path, _) in BUILDS.items():
            body = _by_name(path, name)["ansible.builtin.shell"]
            self.assertNotIn("--no-cache", body)

    def test_a_cache_discarding_fallback_guards_the_ignore_errors(self) -> None:
        for name, (path, var) in BUILDS.items():
            self.assertTrue(_by_name(path, name).get("ignore_errors"))
            self.assertEqual(len(_fallbacks(path, var)), 1, f"{var} has no fallback")

    def test_the_worst_case_ladder_fits_the_budget(self) -> None:
        budget = int(
            parse_static_env(PROJECT_ROOT / "default.env")[
                "INFINITO_CI_DISTRO_BUDGET_SECONDS"
            ]
        )
        cap = _longest_step_seconds(COMPOSE_WORKFLOW)
        for name, (path, var) in BUILDS.items():
            task = _by_name(path, name)
            worst = (
                task["retries"] * _timeout(task)
                + (task["retries"] - 1) * task["delay"]
                + sum(_timeout(f) for f in _fallbacks(path, var))
            )
            self.assertLess(worst, budget, f"{name} outgrows the sweep budget")
            self.assertLess(worst, cap, f"{name} outgrows the deploy step cap")

    def test_the_registry_exclusion_has_a_single_source(self) -> None:
        self.assertEqual(read_text(str(SWARM)).count("svc-registry-docker"), 1)


if __name__ == "__main__":
    unittest.main()
