from __future__ import annotations

import ast
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-svc-assistant"
GUARD = "ASSISTANT_MODELS_NAMED"
CORE = "00_core.yml"
UNNAMED = {"end_user": "", "consultant": "", "embedding": ""}


def named(models: dict) -> bool:
    """Render the role's guard for *models*.

    Args:
        models: model role (``end_user``, ``consultant``, ``embedding``) to reference.
    """
    expression = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))[GUARD]
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return ast.literal_eval(env.from_string(expression).render(ASSISTANT_MODELS=models))


def core_conditions() -> list[str]:
    """Return the conditions of the task that includes the role's core."""
    tasks = load_yaml_any(str(ROLE / ROLE_FILE_TASKS_MAIN))
    include = next(task for task in tasks if task.get("include_tasks") == CORE)
    return [" ".join(str(condition).split()) for condition in include["when"]]


class TestModelGuard(unittest.TestCase):
    def test_no_named_model_keeps_the_role_off(self) -> None:
        self.assertFalse(named(UNNAMED))

    def test_a_blank_reference_names_no_model(self) -> None:
        self.assertFalse(named({**UNNAMED, "end_user": "  "}))

    def test_any_named_model_runs_the_role_into_the_pin_check(self) -> None:
        self.assertTrue(named({**UNNAMED, "embedding": "assistant-embedding:1.0.0"}))

    def test_the_core_runs_only_with_a_named_model(self) -> None:
        self.assertIn(f"{GUARD} | bool", core_conditions())


if __name__ == "__main__":
    unittest.main()
