import unittest

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

CONSTRUCTOR = PROJECT_ROOT / "tasks" / "stages" / "01_constructor.yml"
PLACEMENT = "./tasks/utils/constructor/placement.yml"
PREFLIGHT = "🛫 Pre-flight checks"


def _carrier(task: dict) -> dict | None:
    args = task.get("applications_carrier")
    return args if isinstance(args, dict) else None


def _parks(task: dict) -> bool:
    args = _carrier(task)
    return args is not None and not args.get("clear", False)


def _clears(task: dict) -> bool:
    args = _carrier(task)
    return args is not None and bool(args.get("clear", False))


class TestConstructorBootstrapCarrier(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = load_yaml_any(str(CONSTRUCTOR))
        self.placement = next(
            index
            for index, task in enumerate(self.tasks)
            if task.get("ansible.builtin.include_tasks") == PLACEMENT
        )
        self.preflight = next(
            index
            for index, task in enumerate(self.tasks)
            if task.get("name") == PREFLIGHT
        )
        self.stage_wide = next(
            index
            for index, task in enumerate(self.tasks)
            if _parks(task) and _carrier(task).get("provider_view")
        )

    def test_the_pre_flight_checks_read_a_carrier_in_every_deploy_mode(self):
        window = self.tasks[self.placement + 1 : self.preflight]
        parks = [task for task in window if _parks(task)]

        self.assertEqual(
            len(parks),
            1,
            "one carrier must be parked between the add_host placement and the "
            "pre-flight checks, or every check renders the SPOT cold",
        )
        self.assertNotIn(
            "when",
            parks[0],
            "the pre-flight checks and the package batch read the SPOT in compose "
            "as in swarm, so the carrier must not depend on the deploy mode",
        )

    def test_the_update_role_runs_with_the_bootstrap_carrier_parked(self):
        update = next(
            index
            for index, task in enumerate(self.tasks)
            if (task.get("ansible.builtin.include_role") or {}).get("name") == "update"
        )
        park = next(
            index
            for index in range(self.placement + 1, self.preflight)
            if _parks(self.tasks[index])
        )

        self.assertTrue(
            park < update < self.preflight,
            "the update role reads the SPOT through lookup('config') in three "
            "tasks, so it must run after the bootstrap carrier and before the "
            "pre-flight checks",
        )

    def test_no_carrier_is_dropped_before_the_stage_wide_park(self):
        window = self.tasks[self.placement + 1 : self.stage_wide]

        self.assertEqual(
            [task["name"] for task in window if _clears(task)],
            [],
        )


if __name__ == "__main__":
    unittest.main()
