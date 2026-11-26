import unittest
from pathlib import Path

from jinja2 import Environment

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

INIT = Path(PROJECT_ROOT) / "roles" / "web-app-keycloak" / "tasks" / "02_init.yml"
ASSERT_NAME = (
    "✅ Assert admin events of '{{ application_id }}' expire after whole days above 0"
)
KEY = "KEYCLOAK_ADMIN_EVENTS_EXPIRATION_DAYS"


def _holds(days: object) -> bool:
    task = next(t for t in load_yaml_any(str(INIT)) if t.get("name") == ASSERT_NAME)
    assertion = task["ansible.builtin.assert"]
    env = Environment(autoescape=True)
    return all(
        bool(env.compile_expression(condition)(**{KEY: days}))
        for condition in assertion["that"]
    )


class TestAdminEventsExpirationAssert(unittest.TestCase):
    def test_a_whole_number_of_days_above_zero_passes(self) -> None:
        self.assertTrue(_holds(365))
        self.assertTrue(_holds(1))

    def test_zero_a_negative_a_fraction_a_string_and_a_bool_are_refused(self) -> None:
        for days in (0, -1, 0.5, "365", True):
            with self.subTest(days=days):
                self.assertFalse(_holds(days))


if __name__ == "__main__":
    unittest.main()
