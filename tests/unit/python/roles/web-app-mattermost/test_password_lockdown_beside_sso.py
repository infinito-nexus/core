from __future__ import annotations

import itertools
import unittest
from types import SimpleNamespace

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles" / "web-app-mattermost" / "tasks"
SETUP = TASKS / "01_setup.yml"
CORE = TASKS / "00_core.yml"
PASSWORD = "declared-administrator-password"


def _lookup(name: str, *_terms: object, **_options: object) -> object:
    if name == "users":
        return SimpleNamespace(
            password=PASSWORD,
            username="administrator",
            email="administrator@infinito.test",
        )
    return "generated-and-discarded"


def _environment() -> Environment:
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = bool
    environment.globals["lookup"] = _lookup
    return environment


def _holds(expression: object, **variables: object) -> bool:
    return bool(_environment().compile_expression(str(expression))(**variables))


def handed_password(sso: bool) -> list[str]:
    """
    Args:
        sso: the role's ``MATTERMOST_OIDC_ENABLED``.

    Returns:
        The names of the ``01_setup.yml`` tasks that run and hand Mattermost
        the declared administrator password.
    """
    handed = []
    for task in load_yaml_any(str(SETUP)):
        stdin = (task.get("args") or {}).get("stdin")
        if stdin is None or not _holds(
            task.get("when", True), MATTERMOST_OIDC_ENABLED=sso
        ):
            continue
        rendered = _environment().from_string(stdin).render(MATTERMOST_OIDC_ENABLED=sso)
        if rendered == PASSWORD:
            handed.append(task["name"])
    return handed


class TestTheAdministratorHoldsNoPasswordBesideSso(unittest.TestCase):
    def test_sso_hands_mattermost_no_administrator_password(self) -> None:
        self.assertEqual([], handed_password(sso=True))

    def test_native_mode_still_realigns_the_password(self) -> None:
        self.assertNotEqual([], handed_password(sso=False))


class TestEmailSignUpStaysOffBesideSso(unittest.TestCase):
    def test_the_deploy_refuses_registration_beside_sso_before_the_stack(
        self,
    ) -> None:
        tasks = load_yaml_any(str(CORE))
        guard = next(
            (
                index
                for index, task in enumerate(tasks)
                if "MATTERMOST_LOGIN_REGISTRATION"
                in str(task.get("ansible.builtin.assert"))
            ),
            None,
        )
        self.assertIsNotNone(guard)
        stack = next(
            index
            for index, task in enumerate(tasks)
            if (task.get("include_role") or {}).get("tasks_from") == "consumer.yml"
        )
        self.assertLess(guard, stack)
        that = tasks[guard]["ansible.builtin.assert"]["that"]
        for sso, registration in itertools.product((True, False), repeat=2):
            with self.subTest(sso=sso, registration=registration):
                self.assertIs(
                    not (sso and registration),
                    all(
                        _holds(
                            condition,
                            MATTERMOST_OIDC_ENABLED=sso,
                            MATTERMOST_LOGIN_REGISTRATION=registration,
                        )
                        for condition in that
                    ),
                )


if __name__ == "__main__":
    unittest.main()
