import itertools
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications import login
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/web-app-penpot"
MAIN = load_yaml_any(str(ROLE_DIR / ROLE_FILE_TASKS_MAIN))
ADMINISTRATOR = load_yaml_any(str(ROLE_DIR / "tasks/01_administrator.yml"))
PLATFORM_PASSWORD = "platform-password"
THROWAWAY_PASSWORD = "throwaway-password"


def _lookup(name, *args, **kwargs):
    if name != "ansible.builtin.password":
        raise AssertionError(f"unexpected lookup {name!r}")
    return THROWAWAY_PASSWORD


def _environment():
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    env.globals["lookup"] = _lookup
    return env


def _conditions(task):
    when = task.get("when", [])
    return when if isinstance(when, list) else [when]


def _runs(task, **variables):
    env = _environment()
    return all(
        env.compile_expression(condition)(**variables)
        for condition in _conditions(task)
    )


def _task(tasks, needle):
    return next(task for task in tasks if needle in str(task))


def _login_methods(sso, ldap):
    return {
        "PENPOT_LOGIN_SSO": login.default("sso", sso, ldap),
        "PENPOT_LOGIN_LDAP": login.default("ldap", sso, ldap),
        "PENPOT_LOGIN_NATIVE": login.default("native", sso, ldap),
    }


class TestAdministratorBootstrap(unittest.TestCase):
    def test_the_profile_exists_at_deploy_whenever_sso_does_not_register_it(self):
        bootstrap = _task(MAIN, "01_administrator.yml")
        for sso, ldap in itertools.product((True, False), repeat=2):
            with self.subTest(sso=sso, ldap=ldap):
                self.assertEqual(
                    not sso,
                    _runs(bootstrap, IS_STACK_HOST=True, **_login_methods(sso, ldap)),
                )

    def test_only_native_login_hands_the_platform_password_to_create_profile(self):
        stdin = _task(ADMINISTRATOR, "create-profile")["ansible.builtin.shell"]["stdin"]
        env = _environment()
        for native, expected in (
            (True, PLATFORM_PASSWORD),
            (False, THROWAWAY_PASSWORD),
        ):
            with self.subTest(native=native):
                self.assertEqual(
                    expected,
                    env.from_string(stdin)
                    .render(
                        PENPOT_ADMIN_PASSWORD=PLATFORM_PASSWORD,
                        PENPOT_LOGIN_NATIVE=native,
                    )
                    .strip(),
                )

    def test_only_native_login_resets_the_password_of_an_existing_profile(self):
        update = _task(ADMINISTRATOR, "update-profile")
        existing = {"stdout": "", "stderr": "profile already exists", "rc": 1}
        self.assertTrue(
            _runs(update, PENPOT_LOGIN_NATIVE=True, penpot_admin_create=existing)
        )
        self.assertFalse(
            _runs(update, PENPOT_LOGIN_NATIVE=False, penpot_admin_create=existing)
        )


if __name__ == "__main__":
    unittest.main()
