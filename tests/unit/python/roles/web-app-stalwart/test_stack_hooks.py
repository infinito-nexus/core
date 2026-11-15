from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles" / "web-app-stalwart" / "tasks"
GUARD = "utils/stack/guard.yml"
STAGE = "utils/stack/stage.yml"
CORE = "00_core.yml"


def _tasks(rel: str) -> list[dict]:
    return load_yaml_any(str(TASKS / rel), default_if_missing=[])


def _names(rel: str) -> list[str]:
    return [task.get("name", "") for task in _tasks(rel)]


def _includes(rel: str) -> list[str]:
    return [str(task.get("include_tasks", "")) for task in _tasks(rel)]


class TestStalwartStackHooks(unittest.TestCase):
    def test_the_guard_holds_the_domain_and_login_refusals(self) -> None:
        self.assertEqual(
            _names(GUARD),
            [
                "✅ Assert the mail domain is provisionable by Stalwart",
                "🛑 Refuse login methods Stalwart's directory cannot honour",
            ],
        )

    def test_the_stage_checks_the_store_first_and_frees_smtp(self) -> None:
        includes = _includes(STAGE)
        self.assertEqual(includes[0], "store_guard.yml")
        self.assertTrue(
            any(
                "roles/sys-svc-mail-smtp/tasks/disable.yml" in path for path in includes
            )
        )

    def test_the_core_keeps_no_check_or_stage_step(self) -> None:
        moved = {*_names(GUARD), *_names(STAGE)}
        self.assertEqual(moved & set(_names(CORE)), set())
        self.assertNotIn("store_guard.yml", _includes(CORE))


if __name__ == "__main__":
    unittest.main()
