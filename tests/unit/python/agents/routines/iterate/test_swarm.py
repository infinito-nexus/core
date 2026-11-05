from __future__ import annotations

import unittest

from agents.routines.iterate.swarm import DEFAULT_DISABLE, STEPS
from utils.cache.files import PROJECT_ROOT
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)

_STEPS = {step.id: step for step in STEPS}


class TestSwarmRoutineOpening(unittest.TestCase):
    def test_the_row_check_opens_the_routine(self) -> None:
        self.assertEqual(STEPS[0].id, "row")
        self.assertEqual(STEPS[0].kind, "decision")

    def test_an_own_row_goes_straight_to_disable(self) -> None:
        self.assertEqual(_STEPS["row"].branches[0], ("own row", "disable"))

    def test_a_host_mode_only_role_goes_to_the_host_ranking(self) -> None:
        self.assertIn(("host-mode only", "host"), _STEPS["row"].branches)

    def test_host_step_names_the_ranking_command(self) -> None:
        self.assertIn(
            "python -m cli.meta.ci.host_rows --provides <service key> --mode swarm",
            _STEPS["host"].label,
        )

    def test_host_step_keeps_one_heavy_host(self) -> None:
        self.assertIn("keep one heavy host", _STEPS["host"].label)

    def test_disable_is_asked_between_host_and_deploy(self) -> None:
        self.assertEqual(_STEPS["host"].nxt, "disable")
        self.assertEqual(_STEPS["disable"].kind, "ask")
        self.assertEqual(_STEPS["disable"].nxt, "deploy")

    def test_disable_step_names_every_default_key(self) -> None:
        self.assertIn(", ".join(DEFAULT_DISABLE), _STEPS["disable"].label)

    def test_disable_step_drops_unconsumed_providers(self) -> None:
        self.assertIn(
            "every provider the role under test does not consume",
            _STEPS["disable"].label,
        )

    def test_default_keys_are_registered_services(self) -> None:
        registry = build_service_registry_from_roles_dir(PROJECT_ROOT / "roles")
        for key in DEFAULT_DISABLE:
            with self.subTest(key=key):
                self.assertIn(key, registry)


if __name__ == "__main__":
    unittest.main()
