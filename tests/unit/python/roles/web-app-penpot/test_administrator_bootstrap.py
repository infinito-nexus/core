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
SCHEMA_READERS = ("01_administrator.yml", "02_rbac.yml")


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


def _holds(conditions, **variables):
    env = _environment()
    return all(
        env.compile_expression(condition)(**variables) for condition in conditions
    )


def _runs(task, **variables):
    return _holds(_conditions(task), **variables)


def _task(tasks, needle):
    return next(task for task in tasks if needle in str(task))


def _steps(tasks, inherited=()):
    steps = []
    for task in tasks:
        conditions = (*inherited, *_conditions(task))
        if "block" in task:
            steps.extend(_steps(task["block"], conditions))
        else:
            steps.append((task, conditions))
    return steps


def _includes(task, target, **expected_vars):
    include = str(task.get("ansible.builtin.include_tasks", ""))
    given = task.get("vars") or {}
    return target in include and all(
        given.get(key) == value for key, value in expected_vars.items()
    )


def _is_backend_resolver(task):
    return _includes(
        task, "swarm/resolve_host_cid.yml", resolve_output_prefix="PENPOT_BACKEND"
    )


def _is_backend_port_wait(task):
    return _includes(
        task,
        "wait_container_port.yml",
        wait_output_prefix="PENPOT_BACKEND",
        wait_port="{{ PENPOT_BACKEND_INTERNAL_PORT }}",
    )


def _is_schema_reader(task):
    return any(_includes(task, reader) for reader in SCHEMA_READERS)


def _backend_ready_before_schema_readers(steps, **variables):
    def first(matches):
        return next(
            (
                index
                for index, (task, conditions) in enumerate(steps)
                if matches(task) and _holds(conditions, **variables)
            ),
            None,
        )

    resolver = first(_is_backend_resolver)
    wait = first(_is_backend_port_wait)
    readers = [
        index for index, (task, _) in enumerate(steps) if _is_schema_reader(task)
    ]
    if resolver is None or wait is None or not readers:
        return False
    return resolver < wait < min(readers)


def _broken_shapes(steps):
    wait = next(step for step in steps if _is_backend_port_wait(step[0]))
    bootstrap = next(
        conditions
        for task, conditions in steps
        if _includes(task, "01_administrator.yml")
    )
    others = [step for step in steps if step is not wait]
    return {
        "missing": others,
        "gated_on_the_bootstrap": [
            (wait[0], bootstrap) if step is wait else step for step in steps
        ],
        "after_the_readers": [*others, wait],
    }


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


class TestBackendReadiness(unittest.TestCase):
    def test_the_backend_has_migrated_before_any_task_reads_its_schema(self):
        steps = _steps(MAIN)
        for sso, ldap in itertools.product((True, False), repeat=2):
            with self.subTest(sso=sso, ldap=ldap):
                self.assertTrue(
                    _backend_ready_before_schema_readers(
                        steps, IS_STACK_HOST=True, **_login_methods(sso, ldap)
                    )
                )

    def test_a_wait_that_sso_skips_or_that_runs_late_is_rejected(self):
        for label, shape in _broken_shapes(_steps(MAIN)).items():
            for ldap in (True, False):
                with self.subTest(shape=label, ldap=ldap):
                    self.assertFalse(
                        _backend_ready_before_schema_readers(
                            shape, IS_STACK_HOST=True, **_login_methods(True, ldap)
                        )
                    )


if __name__ == "__main__":
    unittest.main()
