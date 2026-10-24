"""L30: every cron.yml entry has a unique name, a valid UTC cron schedule, an
existing routine, an action of start or pause, and a condition the
orchestrator knows."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import ROLES_DIR, load, role_names
from utils.cache.yaml import dump_yaml_str

ACTIONS = {"start", "pause"}
KNOWN_CONDITIONS = {"host-load-below-30", "host-load-above-95"}
FIELD = re.compile(r"^(\*|[0-9]+)([,\-/][0-9]+)*$|^\*/[0-9]+$|^[0-9]+-[0-9]+$")


def _valid_schedule(value: object) -> bool:
    if not isinstance(value, str):
        return False
    fields = value.split()
    return len(fields) == 5 and all(FIELD.match(f) for f in fields)


def check(roles_dir: Path) -> list[str]:
    problems: list[str] = []
    try:
        from agents.routines import discover

        routines = set(discover())
    except Exception:
        routines = set()
    for role in role_names(roles_dir):
        entries = load(roles_dir / role / "cron.yml") or []
        names: set[str] = set()
        for entry in entries:
            name = entry.get("name")
            if name in names:
                problems.append(f"{role}: duplicate cron name '{name}'")
            names.add(name)
            if not _valid_schedule(entry.get("schedule")):
                problems.append(f"{role}: bad schedule '{entry.get('schedule')}'")
            if routines and entry.get("routine") not in routines:
                problems.append(
                    f"{role}: routine '{entry.get('routine')}' does not exist"
                )
            if entry.get("action") not in ACTIONS:
                problems.append(
                    f"{role}: action '{entry.get('action')}' not start or pause"
                )
            condition = entry.get("condition")
            if condition is not None and condition not in KNOWN_CONDITIONS:
                problems.append(f"{role}: unknown condition '{condition}'")
    return problems


class TestL30(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROLES_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / "bad"
            role.mkdir()
            (role / "cron.yml").write_text(
                dump_yaml_str(
                    [
                        {
                            "name": "x",
                            "schedule": "every night",
                            "routine": "ghost",
                            "action": "go",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
