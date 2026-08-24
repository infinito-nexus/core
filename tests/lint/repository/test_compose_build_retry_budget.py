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
from pathlib import Path

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.env.parser import parse_static_env

from . import PROJECT_ROOT

HANDLERS = PROJECT_ROOT / "roles" / "sys-svc-compose" / "handlers"
SWARM = HANDLERS / "swarm.yml"
COMPOSE = HANDLERS / "compose.yml"
DEPLOY_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy.yml"

BUILDS = {
    "_swarm_pre_deploy_build": SWARM,
    "compose_build": COMPOSE,
}
TIMEOUT_LOOKUP = re.compile(r"lookup\('timeout',\s*(\d+)\s*\)")

ROLE = PROJECT_ROOT / "roles" / "sys-svc-compose"
GATE = "shell/swarm/stack_ready.sh"


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
    """Longest per-step timeout the deploy workflow declares, in seconds.

    Raises instead of falling back: an empty result means the workflow was
    renamed or its step timeouts vanished, and a silent 0 would let any build
    ladder pass the budget assertion below.
    """
    document = load_yaml_any(str(path), default_if_missing={}) or {}
    timeouts = [
        step["timeout-minutes"]
        for job in (document.get("jobs") or {}).values()
        for step in (job.get("steps") or [])
        if "timeout-minutes" in step
    ]
    if not timeouts:
        raise AssertionError(
            f"{path} declares no step-level 'timeout-minutes'; the compose "
            f"build-retry budget is derived from it."
        )
    return 60 * max(timeouts)


def _by_register(path, var):
    task = next((t for t in _tasks(path) if t.get("register") == var), None)
    assert task is not None, f"no task in {path} registers {var}"
    return task


class TestComposeBuildRetryBudget(unittest.TestCase):
    def test_the_ladder_body_does_not_discard_the_cache(self) -> None:
        for var, path in BUILDS.items():
            body = _by_register(path, var)["ansible.builtin.shell"]
            self.assertNotIn("--no-cache", body)

    def test_a_cache_discarding_fallback_guards_the_ignore_errors(self) -> None:
        for var, path in BUILDS.items():
            self.assertTrue(_by_register(path, var).get("ignore_errors"))
            self.assertEqual(len(_fallbacks(path, var)), 1, f"{var} has no fallback")

    def test_the_worst_case_ladder_fits_the_budget(self) -> None:
        budget = int(
            parse_static_env(PROJECT_ROOT / "default.env")[
                "INFINITO_CI_DISTRO_BUDGET_SECONDS"
            ]
        )
        cap = _longest_step_seconds(DEPLOY_WORKFLOW)
        for var, path in BUILDS.items():
            task = _by_register(path, var)
            worst = (
                (1 + task["retries"]) * _timeout(task)
                + task["retries"] * task["delay"]
                + sum(_timeout(f) for f in _fallbacks(path, var))
            )
            self.assertLess(worst, budget, f"{var} outgrows the sweep budget")
            self.assertLess(worst, cap, f"{var} outgrows the deploy step cap")

    def test_every_convergence_gate_waits_the_same_budget(self) -> None:
        """Both callers poll the same script for the same stack, so a budget that
        fits one fits the other. They drifted once -- the handler was raised to
        600 while post_deploy kept a hardcoded 150 -- and the shorter one then
        killed a healthy-but-slow stack on its own."""
        budgets = {}
        for path in sorted(iter_project_files(extensions=(".yml",))):
            if not path.startswith(str(ROLE)):
                continue
            for task in _tasks(path):
                if not isinstance(task, dict):
                    continue
                if GATE in str(task.get("ansible.builtin.script", "")):
                    rel = Path(path).relative_to(PROJECT_ROOT)
                    budgets[f"{rel}:{task.get('name')}"] = (
                        str(task.get("retries")),
                        str(task.get("delay")),
                    )
        self.assertGreaterEqual(len(budgets), 2, f"gate callers not found: {budgets}")
        self.assertEqual(
            len(set(budgets.values())),
            1,
            f"convergence gate callers disagree on their budget: {budgets}",
        )

    def test_the_registry_exclusion_has_a_single_source(self) -> None:
        self.assertEqual(read_text(str(SWARM)).count("svc-registry-docker"), 1)


if __name__ == "__main__":
    unittest.main()
