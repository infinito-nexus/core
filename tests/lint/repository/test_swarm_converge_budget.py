"""Contract of the swarm convergence gate's callers.

Both callers poll the same ``stack_ready.sh`` for the same stack, so a budget
that fits one fits the other. They drifted once - the handler was overridable
while post_deploy kept a hardcoded 150 - and the shorter one then killed a
healthy-but-slow stack. Pinned here: both read the single declared budget, both
give up at once on the gate's terminal rc 2 instead of waiting it out, the
worst-case wall clock of one gate stays inside the sweep budget, and no role
re-declares the budget at a value the declaration no longer carries.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.env.parser import parse_static_env
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

COMPOSE = PROJECT_ROOT / "roles" / "sys-svc-compose"
CALLERS = (
    COMPOSE / "handlers" / "swarm.yml",
    COMPOSE / "tasks" / "utils" / "post_deploy.yml",
)
BUDGET = PROJECT_ROOT / "group_vars" / "all" / "18_swarm.yml"


def _gate_tasks(path):
    return [
        task
        for task in (load_yaml_any(str(path), default_if_missing=[]) or [])
        if "stack_ready.sh" in str(task.get("ansible.builtin.script", ""))
    ]


class TestSwarmConvergeBudget(unittest.TestCase):
    def test_every_caller_reads_the_declared_budget(self) -> None:
        for path in CALLERS:
            tasks = _gate_tasks(path)
            self.assertEqual(len(tasks), 1, f"{path} does not call the gate once")
            self.assertEqual(
                tasks[0]["retries"], "{{ swarm_stack_converge_retries }}", str(path)
            )

    def test_every_caller_gives_up_on_a_terminal_gate_verdict(self) -> None:
        for path in CALLERS:
            self.assertIn("rc in [0, 2]", _gate_tasks(path)[0]["until"], str(path))

    def test_every_caller_passes_the_declared_grace(self) -> None:
        for path in CALLERS:
            self.assertEqual(
                _gate_tasks(path)[0]["environment"]["FATAL_GRACE"],
                "{{ swarm_stack_fatal_grace }}",
                str(path),
            )

    def test_the_budget_is_declared_once_and_fits_the_sweep(self) -> None:
        retries = load_yaml_any(str(BUDGET), default_if_missing={})[
            "swarm_stack_converge_retries"
        ]
        delay = _gate_tasks(CALLERS[0])[0]["delay"]
        sweep = int(
            parse_static_env(PROJECT_ROOT / "default.env")[
                "INFINITO_CI_DISTRO_BUDGET_SECONDS"
            ]
        )
        self.assertLess(retries * delay, sweep)

    def test_the_grace_fits_inside_the_budget(self) -> None:
        declared = load_yaml_any(str(BUDGET), default_if_missing={})
        delay = _gate_tasks(CALLERS[0])[0]["delay"]
        self.assertLess(
            declared["swarm_stack_fatal_grace"],
            declared["swarm_stack_converge_retries"] * delay,
        )

    def test_no_role_shadows_the_budget_with_a_different_value(self) -> None:
        declared = load_yaml_any(str(BUDGET), default_if_missing={})[
            "swarm_stack_converge_retries"
        ]
        for path in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_VARS_MAIN}")):
            shadow = (load_yaml_any(str(path), default_if_missing={}) or {}).get(
                "swarm_stack_converge_retries"
            )
            if shadow is not None:
                self.assertEqual(shadow, declared, str(path))


if __name__ == "__main__":
    unittest.main()
