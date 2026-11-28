import unittest

from jinja2 import Environment

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "web-app-matomo" / "tasks"
TOKEN = "0123456789abcdef0123456789abcdef"


def _tasks(relative: str) -> list[dict]:
    return load_yaml_any(str(TASKS / relative)) or []


def _steps(tasks: list[dict], inherited: list) -> list[dict]:
    """Args:
    tasks: a task list that may hold blocks.
    inherited: the when conditions of the blocks around ``tasks``.

    Returns:
    the leaf tasks, each with the conditions of its blocks ahead of its own.
    """
    steps: list[dict] = []
    for task in tasks:
        when = task.get("when", [])
        conditions = inherited + (when if isinstance(when, list) else [when])
        if "block" in task:
            steps += _steps(task["block"], conditions)
        else:
            steps.append({**task, "when": conditions})
    return steps


def _include(relative: str, target: str) -> dict:
    return next(
        task
        for task in _steps(_tasks(relative), [])
        if target
        in str(task.get("include_tasks", task.get("ansible.builtin.include_tasks")))
    )


def _runs(task: dict, installed: bool, stored: str) -> bool:
    """Args:
    task: an include task of ``03_install_path.yml``.
    installed: what the install-state probe reported.
    stored: the token the token store holds, empty for none.
    """
    when = task["when"]
    context = {
        "matomo_install_state": {"stdout": "installed\n" if installed else "fresh\n"},
        "lookup": lambda *_: {"tokens": {"web-app-matomo": stored} if stored else {}},
    }
    env = Environment(autoescape=True)
    return all(
        bool(env.compile_expression(expression)(**context))
        for expression in (when if isinstance(when, list) else [when])
    )


class TestTokenPath(unittest.TestCase):
    def setUp(self):
        self.bootstrap = _include("03_install_path.yml", "04_bootstrap.yml")
        self.mint = _include("03_install_path.yml", "utils/mint_token.yml")

    def test_a_fresh_install_bootstraps_whatever_the_store_holds(self):
        for stored in ("", TOKEN):
            with self.subTest(stored=stored):
                self.assertTrue(_runs(self.bootstrap, False, stored))
                self.assertFalse(_runs(self.mint, False, stored))

    def test_an_existing_install_without_a_stored_token_mints_one_instead(self):
        self.assertFalse(_runs(self.bootstrap, True, ""))
        self.assertTrue(_runs(self.mint, True, ""))

    def test_an_existing_install_with_a_stored_token_does_neither(self):
        self.assertFalse(_runs(self.bootstrap, True, TOKEN))
        self.assertFalse(_runs(self.mint, True, TOKEN))

    def test_both_paths_persist_through_the_one_token_store_include(self):
        self.assertTrue(_include("04_bootstrap.yml", "utils/store_token.yml"))
        self.assertTrue(_include("utils/mint_token.yml", "store_token.yml"))
        mint = _tasks("utils/mint_token.yml")[0]
        self.assertEqual(
            "{{ lookup('file', 'php/mint_token_auth.php') }}",
            mint["ansible.builtin.shell"]["stdin"],
        )
        self.assertEqual("{{ MASK_CREDENTIALS_IN_LOGS | bool }}", mint["no_log"])


if __name__ == "__main__":
    unittest.main()
