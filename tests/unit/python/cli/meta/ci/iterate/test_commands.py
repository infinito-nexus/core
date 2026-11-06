from __future__ import annotations

import re
import unittest

from agents.routines.iterate import compose as routine
from cli.meta.ci.iterate import commands, plan
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles import redeploy
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

APP = "web-app-a"
OTHER = "web-app-b"


def _path(role: str, rel: str) -> str:
    return f"roles/{role}/{rel}"


KINDS = sorted(
    redeploy.INVENTORY_FILES
    | redeploy.OUTSIDE_SYNC_FILES
    | routine._INVENTORY_FILES
    | routine._OUTSIDE_SYNC_FILES
    | {
        f"{folder}x.py"
        for folder in {*redeploy.OUTSIDE_SYNC_DIRS, *routine._OUTSIDE_SYNC_DIRS}
    }
    | {ROLE_FILE_TASKS_MAIN}
)
NO_DEPLOY = ("tests/unit/python/x.py", "docs/x.md", "README.md", "docs/x.rst")
CASES = (
    *((APP, [_path(role, kind)]) for kind in KINDS for role in (APP, OTHER)),
    *((APP, [_path(APP, ROLE_FILE_TASKS_MAIN), path]) for path in NO_DEPLOY),
    *((APP, [path]) for path in NO_DEPLOY),
    (APP, [_path(APP, "README.md")]),
    (APP, [_path(APP, ROLE_FILE_TASKS_MAIN), _path(OTHER, ROLE_FILE_TASKS_MAIN)]),
    (APP, ["plugins/filter/x.py"]),
    (APP, []),
    ("", [_path(APP, ROLE_FILE_TASKS_MAIN)]),
)
ROUTINE_LABEL = {
    routine.ROLE_SYNC: commands.ROLE_SYNC,
    routine.UPDATE: commands.UPDATE,
    routine.REBUILD: commands.REINSTALL,
}


class TestRedeployMatchesTheComposeRoutine(unittest.TestCase):
    def test_every_file_kind_takes_the_routines_branch(self) -> None:
        for role, paths in CASES:
            with self.subTest(role=role, paths=paths):
                self.assertEqual(
                    commands.redeploy(role, paths),
                    ROUTINE_LABEL[routine.redeploy_target(role, paths)],
                )

    def test_pin_covers_every_inventory_baked_file_kind(self) -> None:
        self.assertLessEqual(
            redeploy.INVENTORY_FILES | redeploy.OUTSIDE_SYNC_FILES, set(KINDS)
        )


class TestCommand(unittest.TestCase):
    def _command(self, deploy, **extra):
        values = {
            "variant": 1,
            "variants": 2,
            "disable": "matomo",
            "network": "multi",
        }
        values.update(extra)
        return commands.command(deploy, "web-app-a", **values)

    def test_update_pins_the_variant_of_a_matrix_role(self) -> None:
        self.assertEqual(
            self._command(commands.UPDATE),
            "make compose-deploy mode=update apps=web-app-a variant=1 disable=matomo",
        )

    def test_single_variant_role_takes_no_variant_in_compose(self) -> None:
        self.assertNotIn("variant=", self._command(commands.REINSTALL, variants=1))

    def test_gate_runs_every_variant(self) -> None:
        self.assertEqual(
            self._command(commands.GATE),
            "make compose-deploy mode=reinstall apps=web-app-a full_cycle=true disable=matomo",
        )

    def test_swarm_row_always_pins_variant_and_network(self) -> None:
        self.assertEqual(
            self._command(commands.ZOMBIE, variants=1),
            "make swarm-zombie app=web-app-a variant=1 network=multi disable=matomo",
        )

    def test_role_sync_takes_no_disable(self) -> None:
        self.assertEqual(
            self._command(commands.ROLE_SYNC),
            "make compose-role-sync role=web-app-a variant=1",
        )

    def test_empty_values_are_left_out(self) -> None:
        self.assertEqual(
            self._command(commands.ROUNDTRIP, disable=""), "make roundtrip"
        )

    def test_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._command("deploy-everything")


class TestDefaultDisableMatchesTheComposeSkill(unittest.TestCase):
    def test_the_skill_documents_the_same_keys(self) -> None:
        skill = read_text(
            str(PROJECT_ROOT / "agents" / "skills" / "i8-iterate-compose" / "SKILL.md")
        )
        documented = re.search(r"Default `disable=([^`]+)`", skill)
        self.assertIsNotNone(documented)
        self.assertEqual(tuple(documented.group(1).split(",")), plan.DEFAULT_DISABLE)


if __name__ == "__main__":
    unittest.main()
