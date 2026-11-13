import unittest

from jinja2 import Environment, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "sys-service"
RUNTIME = load_yaml_any(str(ROLE / ROLE_FILE_DEFAULTS_MAIN))[
    "SYS_SERVICE_DEFAULT_RUNTIME"
]


def _start_timeout(unit_type: str) -> str:
    expression = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))[
        "system_service_tpl_timeout_start_sec"
    ]
    return (
        Environment(autoescape=select_autoescape())
        .from_string(expression)
        .render(system_service_tpl_type=unit_type, SYS_SERVICE_DEFAULT_RUNTIME=RUNTIME)
    )


class TestOneshotStartTimeout(unittest.TestCase):
    def test_a_oneshot_unit_gets_a_bounded_start(self) -> None:
        self.assertTrue(RUNTIME)
        self.assertEqual(_start_timeout("oneshot"), RUNTIME)

    def test_other_unit_types_keep_the_manager_default(self) -> None:
        self.assertEqual(_start_timeout("simple"), "")


if __name__ == "__main__":
    unittest.main()
