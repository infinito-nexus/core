"""Each application that can enforce its own second factor renders the
enforcement from ``login.method.2fa.enforced``.

Every render goes through the role's real ``vars/main.yml`` and the real
``config`` lookup, with the override in ``applications`` the way an inventory
sets it, and the deployed roles in ``group_names`` picking the mode.
"""

from __future__ import annotations

import json
import os
import re
import runpy
import sys
import unittest
import unittest.mock as mock
from itertools import pairwise
from typing import Any

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache import applications as applications_cache
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.reset import _reset_rendered_caches_for_tests
from utils.cache.yaml import load_yaml_str
from utils.roles.applications.converge import values
from utils.roles.applications.forms import when_path
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_VARS_MAIN

ROLES = PROJECT_ROOT / "roles"
SSO = ("web-app-keycloak", "svc-db-openldap")
NATIVE = ()
ENFORCEMENT_OFF = {"enforced": False}
ENFORCEMENT_ON = {"enforced": True}
BESIDE_KEYCLOAK = {"enabled": True}


def _unrendered(value: Any, **_context: Any) -> Any:
    return value


_EAGER_RENDER = mock.patch.object(
    applications_cache, "_render_with_templar", new=_unrendered
)


def setUpModule() -> None:
    _reset_rendered_caches_for_tests()
    _EAGER_RENDER.start()


def tearDownModule() -> None:
    _EAGER_RENDER.stop()
    _reset_rendered_caches_for_tests()


def render(
    role: str,
    template: str,
    mode: tuple[str, ...],
    entity: str,
    second_factor: dict[str, bool],
    methods: dict[str, dict[str, bool]] | None = None,
) -> Any:
    """Render *template* in *role*'s variable scope.

    Args:
        role: the application whose ``vars/main.yml`` is in scope.
        template: Jinja text.
        mode: the roles deployed next to *role*.
        entity: the entity whose ``login.method.2fa`` the override targets.
        second_factor: the inventory override of ``login.method.2fa``.
        methods: inventory overrides of other login methods, keyed by method.
    """
    overrides = {
        **(methods or {}),
        **({"2fa": dict(second_factor)} if second_factor else {}),
    }
    applications = (
        {role: {"services": {entity: {"login": {"method": overrides}}}}}
        if overrides
        else {}
    )
    loader = DataLoader()
    variables = {
        **loader.load_from_file(
            str(ROLES / role / ROLE_FILE_VARS_MAIN), trusted_as_template=True
        ),
        "group_names": sorted({role, *mode}),
        "applications": applications,
    }
    return Templar(loader=loader, variables=variables).template(
        trust_as_template(template)
    )


def line_with(role: str, relative: str, marker: str) -> str:
    """The one stripped line of a role file that contains *marker*.

    Args:
        role: the role that ships the file.
        relative: the file's path below the role.
        marker: text the line holds, such as ``NAME=``.
    """
    lines = [
        line.strip()
        for line in read_text(str(ROLES / role / relative)).splitlines()
        if marker in line
    ]
    if len(lines) != 1:
        raise AssertionError(f"{role}/{relative}: {len(lines)} lines hold {marker!r}")
    return lines[0]


def value_of(line: str) -> str:
    return line.split("=", 1)[1]


class _EnforcementCase:
    """Args:
    ON: the rendered setting while the deploy enforces the second factor.
    OFF: the rendered setting while the deploy only offers it.
    UNMANAGED: the rendered setting while the app's own 2fa is off, which
        leaves the app setting as an admin set it.
    MODE: roles deployed in every mode beside the ones the test picks.
    """

    ROLE: str
    ENTITY: str
    ON: str
    OFF: str
    UNMANAGED: str
    MODE: tuple[str, ...] = ()
    DEFAULT_ENFORCED = True

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        raise NotImplementedError

    def _in(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        return self._value((*mode, *self.MODE), second_factor)

    def _default(self) -> str:
        return self.ON if self.DEFAULT_ENFORCED else self.OFF

    def test_native_mode_follows_the_role_default(self) -> None:
        self.assertEqual(self._default(), self._in(NATIVE, {}))

    def test_an_enforcement_override_only_offers_it(self) -> None:
        self.assertEqual(self.OFF, self._in(NATIVE, ENFORCEMENT_OFF))

    def test_an_enforcement_override_enforces_it(self) -> None:
        self.assertEqual(self.ON, self._in(NATIVE, ENFORCEMENT_ON))

    def test_sso_mode_leaves_the_app_setting_untouched(self) -> None:
        self.assertEqual(self.UNMANAGED, self._in(SSO, {}))

    def test_an_own_second_factor_beside_keycloak_follows_the_default(self) -> None:
        self.assertEqual(self._default(), self._in(SSO, BESIDE_KEYCLOAK))

    def test_an_own_second_factor_beside_keycloak_manages_the_setting(self) -> None:
        self.assertEqual(
            self.OFF, self._in(SSO, {**BESIDE_KEYCLOAK, **ENFORCEMENT_OFF})
        )


class _EnvironmentLine(_EnforcementCase):
    RELATIVE = "templates/env.j2"
    MARKER: str

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        line = line_with(self.ROLE, self.RELATIVE, self.MARKER)
        rendered = render(self.ROLE, line, mode, self.ENTITY, second_factor)
        return "" if rendered is None else rendered.strip()


class TestGitea(_EnvironmentLine, unittest.TestCase):
    ROLE = "web-app-gitea"
    ENTITY = "gitea"
    MARKER = "GITEA__security__TWO_FACTOR_AUTH="
    ON = "GITEA__security__TWO_FACTOR_AUTH=enforced"
    OFF = "GITEA__security__TWO_FACTOR_AUTH="
    UNMANAGED = OFF
    DEFAULT_ENFORCED = False

    def test_a_passkey_keeps_mfa_manageable_and_the_setting_untouched(self) -> None:
        line = line_with(self.ROLE, self.RELATIVE, self.MARKER)
        rendered = render(
            self.ROLE, line, SSO, self.ENTITY, {}, {"passkey": {"enabled": True}}
        )
        self.assertEqual("", "" if rendered is None else rendered.strip())


class TestWeblate(_EnvironmentLine, unittest.TestCase):
    ROLE = "web-app-weblate"
    ENTITY = "weblate"
    MARKER = "WEBLATE_LOGIN_2FA_ENFORCED="
    ON = "WEBLATE_LOGIN_2FA_ENFORCED=1"
    OFF = "WEBLATE_LOGIN_2FA_ENFORCED=0"
    UNMANAGED = OFF


class TestPgadmin(_EnvironmentLine, unittest.TestCase):
    ROLE = "web-app-pgadmin"
    ENTITY = "pgadmin"
    MARKER = "PGADMIN_CONFIG_MFA_FORCE_REGISTRATION="
    ON = "PGADMIN_CONFIG_MFA_FORCE_REGISTRATION=True"
    OFF = "PGADMIN_CONFIG_MFA_FORCE_REGISTRATION=False"
    UNMANAGED = OFF


class TestEspocrm(_EnforcementCase, unittest.TestCase):
    ROLE = "web-app-espocrm"
    ENTITY = "espocrm"
    FORM = "authentication"
    MARKER = "ESPOCRM_SEED_AUTH2_F_A_FORCED="
    ON = "ESPOCRM_SEED_AUTH2_F_A_FORCED=true"
    OFF = "ESPOCRM_SEED_AUTH2_F_A_FORCED=false"
    UNMANAGED = OFF

    def _seed(
        self, marker: str, mode: tuple[str, ...], second_factor: dict[str, bool]
    ) -> str:
        forms = load_yaml_str(read_text(str(ROLES / self.ROLE / ROLE_FILE_META_FORMS)))
        application: dict[str, Any] = {}
        for spec in forms[self.FORM]["fields"].values():
            for path in filter(None, (spec["source"], when_path(spec.get("when")))):
                *parents, leaf = path.split(".")
                node = application
                for parent in parents:
                    node = node.setdefault(parent, {})
                node[leaf] = render(
                    self.ROLE,
                    f"{{{{ lookup('config', '{self.ROLE}', '{path}') }}}}",
                    mode,
                    self.ENTITY,
                    second_factor,
                )
        block = re.search(
            r"^\{% for espocrm_field.*?^\{% endfor %\}\n",
            read_text(str(ROLES / self.ROLE / "templates/env.j2")),
            re.MULTILINE | re.DOTALL,
        ).group(0)
        rendered = Templar(
            loader=DataLoader(),
            variables={
                "ESPOCRM_FORM_SETTINGS": values(self.FORM, forms, application, {})
            },
        ).template(trust_as_template(block))
        return next(line for line in rendered.splitlines() if line.startswith(marker))

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        return self._seed(self.MARKER, mode, second_factor)

    def test_turning_2fa_off_disables_the_method_in_the_same_seed(self) -> None:
        self.assertEqual(
            "ESPOCRM_SEED_AUTH2_F_A=false",
            self._seed("ESPOCRM_SEED_AUTH2_F_A=", SSO, {}),
        )

    def test_the_seed_name_becomes_the_espocrm_setting(self) -> None:
        suffix = self.MARKER.removeprefix("ESPOCRM_SEED_").rstrip("=").lower()
        first, *rest = suffix.split("_")
        self.assertEqual("auth2FAForced", first + "".join(p.capitalize() for p in rest))
        seeder = read_text(str(ROLES / self.ROLE / "files/php/seed/config.php"))
        self.assertIn("strpos($envKey, 'ESPOCRM_SEED_') !== 0", seeder)


class TestDiscourse(_EnforcementCase, unittest.TestCase):
    ROLE = "web-app-discourse"
    ENTITY = "discourse"
    ON = "all"
    OFF = "no"
    UNMANAGED = OFF
    TASKS = "tasks/stack_host/02_credentials.yml"

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        line = line_with(
            self.ROLE, self.TASKS, "-e DISCOURSE_ENFORCE_SECOND_FACTOR="
        ).removeprefix("-e ")
        return value_of(render(self.ROLE, line, mode, self.ENTITY, second_factor))

    READBACK = "🛑 Refuse an instance the rotated credentials did not reach"
    APPLIED = (
        "administrator_present=true",
        "administrator_admin=true",
        "administrator_active=true",
        "administrator_password_matches=true",
        "login_methods_applied=true",
        "second_factor_enforcement_applied=true",
    )

    def _refused(self, lines: list[str]) -> bool:
        """Args:
            lines: stdout lines of ``verify_settings.rb``.

        Returns:
            Whether the deploy's readback assert fails on them.
        """
        tasks = load_yaml_str(read_text(str(ROLES / self.ROLE / self.TASKS)))
        conditions = next(task for task in tasks if task["name"] == self.READBACK)[
            "ansible.builtin.assert"
        ]["that"]
        templar = Templar(
            loader=DataLoader(),
            variables={
                "discourse_settings_readback": {"stdout_lines": lines},
                "DISCOURSE_OIDC_ENABLED": False,
                "RBAC": {"GROUP": {"CLAIM": "groups"}},
            },
        )
        return not all(
            templar.template(trust_as_template(f"{{{{ {condition} }}}}"))
            for condition in conditions
        )

    def test_moving_to_sso_switches_the_enforcement_off(self) -> None:
        self.assertEqual(self.ON, self._in(NATIVE, ENFORCEMENT_ON))
        self.assertEqual(self.OFF, self._in(SSO, {}))

    def test_the_deploy_refuses_an_enforcement_the_readback_misses(self) -> None:
        self.assertFalse(self._refused(list(self.APPLIED)))
        missed = [*self.APPLIED[:-1], "second_factor_enforcement_applied=false"]
        self.assertTrue(self._refused(missed))


class _TaskEnvironment(_EnforcementCase):
    ON = "true"
    OFF = "false"
    UNMANAGED = OFF
    TASKS: str
    NAME: str

    def _task(self) -> dict:
        tasks = load_yaml_str(read_text(str(ROLES / self.ROLE / self.TASKS)))
        return next(
            task
            for task in tasks
            if isinstance(task.get("environment"), dict)
            and self.NAME in task["environment"]
        )

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        template = self._task()["environment"][self.NAME]
        return render(self.ROLE, template, mode, self.ENTITY, second_factor)

    def test_the_container_receives_the_value(self) -> None:  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        task = self._task()
        tokens = task.get("ansible.builtin.command", {}).get("argv") or (
            task.get("ansible.builtin.shell", {})
            .get("cmd", "")
            .replace("\\\n", " ")
            .split()
        )
        forwarded = {value for flag, value in pairwise(tokens) if flag == "-e"}
        self.assertIn(self.NAME, forwarded)


class TestErpnext(_TaskEnvironment, unittest.TestCase):
    ROLE = "web-app-erpnext"
    ENTITY = "erpnext"
    TASKS = "tasks/01_manager_ops.yml"
    NAME = "LOGIN_2FA_ENFORCED"
    MODE = ("web-app-email",)

    def test_without_mail_the_enforcement_is_held(self) -> None:
        self.assertEqual(self.OFF, self._value(NATIVE, {}))
        self.assertEqual(self.OFF, self._value(NATIVE, ENFORCEMENT_ON))

    def test_the_deploy_names_why_it_holds_the_enforcement(self) -> None:
        tasks = load_yaml_str(read_text(str(ROLES / self.ROLE / self.TASKS)))
        notice = next(task for task in tasks if "ansible.builtin.debug" in task)
        self.assertEqual(
            "ERPNEXT_LOGIN_2FA_ENFORCEMENT | bool and not ERPNEXT_EMAIL_ENABLED | bool",
            notice["when"],
        )
        self.assertIn(
            "web-app-email is not deployed", notice["ansible.builtin.debug"]["msg"]
        )


class TestErpnextScript(unittest.TestCase):
    SCRIPT = ROLES / "web-app-erpnext/files/python/apply/login/methods.py"

    def _role_writes(
        self, second_factor: str, enforced: str, current: int = 0
    ) -> list[tuple]:
        frappe = mock.MagicMock()
        frappe.db.get_value.return_value = current
        environment = {
            "SITE_NAME": "site",
            "LOGIN_MODE": "converge",
            "SYSTEM_SETTINGS": "{}",
            "WEBSITE_SETTINGS": "{}",
            "LOGIN_2FA": second_factor,
            "LOGIN_2FA_ENFORCED": enforced,
        }
        with (
            mock.patch.dict(sys.modules, {"frappe": frappe}),
            mock.patch.dict(os.environ, environment),
        ):
            runpy.run_path(str(self.SCRIPT))
        return [call.args for call in frappe.db.set_value.call_args_list]

    def test_an_enforced_second_factor_checks_the_box_of_role_all(self) -> None:
        self.assertEqual(
            [("Role", "All", "two_factor_auth", 1)], self._role_writes("true", "true")
        )

    def test_an_offered_second_factor_clears_the_box(self) -> None:
        self.assertEqual(
            [("Role", "All", "two_factor_auth", 0)], self._role_writes("true", "false")
        )

    def test_without_the_own_second_factor_an_unchecked_box_is_left_alone(
        self,
    ) -> None:
        self.assertEqual([], self._role_writes("false", "false"))
        self.assertEqual([], self._role_writes("false", "true"))

    def test_turning_2fa_off_after_enforcing_clears_the_box(self) -> None:
        self.assertEqual(
            [("Role", "All", "two_factor_auth", 0)],
            self._role_writes("false", "false", current=1),
        )


class TestOdoo(_EnforcementCase, unittest.TestCase):
    ROLE = "web-app-odoo"
    ENTITY = "odoo"
    TASKS = "tasks/08_login_methods.yml"
    MODE = ("web-app-email",)
    ON = "enforce"
    OFF = "offer"
    UNMANAGED = "off"

    def _tasks(self) -> list[dict]:
        return load_yaml_str(read_text(str(ROLES / self.ROLE / self.TASKS)))

    def _policy_task(self) -> dict:
        return next(
            task
            for task in self._tasks()
            if "ODOO_2FA_STATE" in task.get("environment", {})
        )

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        state = self._policy_task()["environment"]["ODOO_2FA_STATE"]
        return render(self.ROLE, state, mode, self.ENTITY, second_factor)

    def test_without_mail_the_enforcement_is_held(self) -> None:
        self.assertEqual("hold", self._value(NATIVE, {}))
        self.assertEqual("hold", self._value(NATIVE, ENFORCEMENT_ON))
        self.assertEqual(self.OFF, self._value(NATIVE, ENFORCEMENT_OFF))

    def test_the_deploy_names_why_it_holds_the_enforcement(self) -> None:
        notices = {
            task["when"]: task
            for task in self._tasks()
            if "ansible.builtin.debug" in task
        }
        reasons = {
            "ODOO_LOGIN_2FA_ENFORCEMENT | bool and not ODOO_EMAIL_ENABLED | bool": (
                "web-app-email is not deployed"
            ),
            "'MAIL=failed' in odoo_two_factor_policy.stdout": (
                "could not open an SMTP session"
            ),
        }
        self.assertEqual(set(reasons), set(notices))
        for when, reason in reasons.items():
            with self.subTest(when=when):
                self.assertTrue(notices[when]["name"].startswith("⚠️ "))
                self.assertIn(reason, notices[when]["ansible.builtin.debug"]["msg"])
        self.assertFalse(any("ansible.builtin.fail" in t for t in self._tasks()))

    def test_the_policy_runs_on_every_deploy_through_the_orm_applier(self) -> None:
        task = self._policy_task()
        self.assertNotIn("when", task)
        self.assertEqual(
            "{{ lookup('ansible.builtin.file', ODOO_TWO_FACTOR_POLICY_SCRIPT) }}",
            task["ansible.builtin.shell"]["stdin"],
        )
        self.assertEqual(
            "all_required",
            render(
                self.ROLE,
                task["environment"]["ODOO_2FA_POLICY"],
                NATIVE,
                self.ENTITY,
                {},
            ),
        )


class TestZammad(_TaskEnvironment, unittest.TestCase):
    ROLE = "web-app-zammad"
    ENTITY = "zammad"
    TASKS = "tasks/01_manager_ops.yml"
    NAME = "LOGIN_2FA_ENFORCED"

    def test_turning_2fa_off_disables_every_method_and_clears_the_enforcement(
        self,
    ) -> None:
        script = read_text(str(ROLES / self.ROLE / "files/ruby/apply/login_methods.rb"))
        for method in ("authenticator_app", "security_keys"):
            with self.subTest(method=method):
                self.assertIn(
                    f'Setting.set("two_factor_authentication_method_{method}",'
                    " second_factor)",
                    script,
                )
        self.assertNotIn("elsif", script)
        self.assertEqual("false", self._value(SSO, {}))


class TestGitlab(_TaskEnvironment, unittest.TestCase):
    ROLE = "web-app-gitlab"
    ENTITY = "gitlab"
    TASKS = "tasks/utils/login_methods.yml"
    NAME = "GITLAB_LOGIN_2FA_ENFORCED"

    def test_the_runner_requires_the_second_factor_only_with_its_own_2fa(self) -> None:
        script = read_text(str(ROLES / self.ROLE / "files/ruby/apply_login_methods.rb"))
        self.assertIn(
            "if ENV.fetch('GITLAB_LOGIN_2FA') == 'true'\n"
            "  wanted[:require_two_factor_authentication] = "
            "ENV.fetch('GITLAB_LOGIN_2FA_ENFORCED') == 'true'\nend\n",
            script,
        )
        self.assertIn(
            "GITLAB_LOGIN_2FA", self._task()["ansible.builtin.command"]["argv"]
        )
        self.assertEqual(
            "false",
            render(
                self.ROLE,
                self._task()["environment"]["GITLAB_LOGIN_2FA"],
                SSO,
                self.ENTITY,
                {},
            ),
        )
        self.assertIn(
            "wanted[:two_factor_grace_period] = 0 if wanted[:require_two_factor_authentication]",
            script,
        )


class TestMatomo(_TaskEnvironment, unittest.TestCase):
    ROLE = "web-app-matomo"
    ENTITY = "matomo"
    TASKS = "tasks/03_install_path.yml"
    NAME = "MATOMO_TWO_FACTOR_MODE"
    ON = "enforced"
    OFF = "offered"
    UNMANAGED = "off"

    def test_the_requirement_converges_on_every_deploy_after_the_plugin_switch(
        self,
    ) -> None:
        tasks = load_yaml_str(read_text(str(ROLES / self.ROLE / self.TASKS)))
        task = self._task()
        switch = next(
            t for t in tasks if t.get("register") == "matomo_two_factor_plugin"
        )
        self.assertNotIn("when", task)
        self.assertLess(tasks.index(switch), tasks.index(task))
        self.assertEqual(
            "{{ lookup('file', 'php/two_factor_required.php') }}",
            task["ansible.builtin.shell"]["stdin"],
        )


class TestPretix(_EnforcementCase, unittest.TestCase):
    ROLE = "web-app-pretix"
    ENTITY = "pretix"
    ON = "PRETIX_PRETIX_OBLIGATORY_2FA=True"
    OFF = ""
    UNMANAGED = OFF
    START = "{% if PRETIX_LOGIN_2FA_ENFORCED | bool %}"

    def _block(self) -> str:
        text = read_text(str(ROLES / self.ROLE / "templates/env.j2"))
        start = text.index(self.START)
        end = text.index("{% endif %}", start) + len("{% endif %}")
        return text[start:end]

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        rendered = render(self.ROLE, self._block(), mode, self.ENTITY, second_factor)
        return "" if rendered is None else rendered.strip()


class TestMoodle(_EnforcementCase, unittest.TestCase):
    ROLE = "web-app-moodle"
    ENTITY = "moodle"
    TASKS = "tasks/05_login_methods.yml"
    ON = "nosetup=0 grace=enforced expired=1"
    OFF = "nosetup=1 grace=offered expired=0"
    UNMANAGED = "nosetup=0 grace=off expired=0"
    GRACE = "-e MOODLE_MFA_GRACE_MODE="

    def _task(self, component: str) -> dict:
        tasks = load_yaml_str(read_text(str(ROLES / self.ROLE / self.TASKS)))
        return next(
            task
            for task in tasks
            if task.get("vars", {}).get("moodle_plugin_config_component") == component
        )

    def _setting(self, component: str, mode, second_factor) -> str:
        task = self._task(component)
        if "when" in task:
            gate = render(
                self.ROLE,
                "{{ " + task["when"] + " }}",
                mode,
                self.ENTITY,
                second_factor,
            )
            if gate not in (True, "True"):
                return "untouched"
        template = task["vars"]["moodle_plugin_config_settings"]["enabled"]
        return str(render(self.ROLE, template, mode, self.ENTITY, second_factor))

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        nosetup = self._setting("factor_nosetup", mode, second_factor)
        line = line_with(self.ROLE, self.TASKS, self.GRACE).removeprefix("-e ")
        grace = value_of(render(self.ROLE, line, mode, self.ENTITY, second_factor))
        expired = self._setting("local_mfaenforce", mode, second_factor)
        return f"nosetup={nosetup} grace={grace} expired={expired}"

    def test_the_email_factor_moodle_enables_by_default_stays_off(self) -> None:
        task = self._task("factor_email")
        self.assertNotIn("when", task)
        self.assertEqual("0", task["vars"]["moodle_plugin_config_settings"]["enabled"])

    def test_the_grace_factor_converges_on_every_deploy_through_its_script(
        self,
    ) -> None:
        tasks = load_yaml_str(read_text(str(ROLES / self.ROLE / self.TASKS)))
        task = next(
            t for t in tasks if self.GRACE in str(t.get("ansible.builtin.shell"))
        )
        self.assertNotIn("when", task)
        self.assertEqual(
            "{{ lookup('file', 'php/provision/mfa_grace.php') }}", task["args"]["stdin"]
        )

    def test_the_plugin_reaches_the_code_volume_before_the_database_upgrade(
        self,
    ) -> None:
        tasks = load_yaml_str(
            read_text(str(ROLES / self.ROLE / "tasks/01_manager_ops.yml"))
        )
        commands = [
            str(task.get("ansible.builtin.shell", task.get("shell", "")))
            for task in tasks
        ]
        sync = next(
            index
            for index, command in enumerate(commands)
            if "MOODLE_MFA_ENFORCE_PLUGIN_DIR" in command
        )
        upgrade = next(
            index for index, command in enumerate(commands) if "upgrade.php" in command
        )
        self.assertLess(sync, upgrade)


class TestJoomla(_EnforcementCase, unittest.TestCase):
    ROLE = "web-app-joomla"
    ENTITY = "joomla"
    TASKS = "tasks/11_login_methods.yml"
    SCRIPT = "files/php/login_methods.php"
    ON = "forceMFAUserGroups=['1']"
    OFF = "forceMFAUserGroups=[]"
    UNMANAGED = "forceMFAUserGroups=[] once no multifactorauth plugin is enabled"
    COUNT = (
        "    ->select('COUNT(*)')\n"
        "    ->from($db->quoteName('#__extensions'))\n"
        "    ->where($db->quoteName('type') . ' = ' . $db->quote('plugin'))\n"
        "    ->where($db->quoteName('folder') . ' = ' . $db->quote('multifactorauth'))\n"
        "    ->where($db->quoteName('enabled') . ' = 1');\n"
        "$methodsLeft = (int) $db->setQuery($query)->loadResult();\n"
    )
    GUARD = (
        "$currentForced = array_map('strval',"
        " (array) ($params['forceMFAUserGroups'] ?? []));\n"
        "if (($secondFactor || $methodsLeft === 0)"
        " && $currentForced !== $forcedGroups) {\n"
        "    $params['forceMFAUserGroups'] = $forcedGroups;\n"
        "    $dirty = true;\n"
        "}\n"
    )

    def _flag(self, marker: str, mode, second_factor) -> str:
        line = line_with(self.ROLE, self.TASKS, marker).removeprefix("-e ")
        return value_of(render(self.ROLE, line, mode, self.ENTITY, second_factor))

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        if self._flag("-e J_LOGIN_2FA=", mode, second_factor) != "1":
            return self.UNMANAGED
        if self._flag("-e J_LOGIN_2FA_ENFORCED=", mode, second_factor) != "1":
            return self.OFF
        group = self._flag("-e J_LOGIN_2FA_ROOT_GROUP=", mode, second_factor)
        return f"forceMFAUserGroups=['{group}']"

    def _script(self) -> str:
        return read_text(str(ROLES / self.ROLE / self.SCRIPT))

    def test_turning_2fa_off_clears_the_list_only_once_no_method_is_left(
        self,
    ) -> None:
        script = self._script()
        self.assertIn(self.COUNT, script)
        loop_end = script.index("$changed = true;\n}\n")
        self.assertLess(loop_end, script.index(self.COUNT))
        self.assertLess(script.index(self.COUNT), script.index(self.GUARD))
        plugins = render(self.ROLE, "{{ JOOMLA_LOGIN_PLUGINS }}", SSO, self.ENTITY, {})
        methods = {k: v for k, v in plugins.items() if k.startswith("multifactorauth/")}
        self.assertEqual({0}, set(methods.values()))
        self.assertEqual(self.UNMANAGED, self._in(SSO, {}))

    def test_a_guard_without_the_method_count_is_caught(self) -> None:
        unguarded = self._script().replace(
            "($secondFactor || $methodsLeft === 0) && ", ""
        )
        self.assertNotIn(self.GUARD, unguarded)


NOT_ENFORCED = "Two-factor authentication is not enforced"
ENFORCED_FOR_ALL = "Two-factor authentication is enforced for all users"
ENFORCED_FOR_GROUP = (
    "Two-factor authentication is enforced for members of the group(s) admin"
)
ENFORCED_EXCEPT = (
    "Two-factor authentication is enforced for all users, except members of admin"
)
TOTP = {"twofactor_totp": "13.0.0"}
WEBAUTHN = {"twofactor_webauthn": "2.0.0"}
PRIVACYIDEA = {"privacyidea": "4.0.0"}


class TestNextcloud(_EnforcementCase, unittest.TestCase):
    ROLE = "web-app-nextcloud"
    ENTITY = "nextcloud"
    TASKS = "tasks/02_manager_ops.yml"
    ON = "True"
    OFF = "False"
    UNMANAGED = OFF

    def _value(self, mode: tuple[str, ...], second_factor: dict[str, bool]) -> str:
        template = "{{ NEXTCLOUD_LOGIN_2FA_ENFORCED | bool }}"
        return str(render(self.ROLE, template, mode, self.ENTITY, second_factor))

    SUBTASKS = "tasks/02_manager_ops/09_twofactor.yml"

    def _include(self) -> dict:
        tasks = load_yaml_str(read_text(str(ROLES / self.ROLE / self.TASKS)))
        return next(
            task
            for task in tasks
            if self.SUBTASKS.removeprefix("tasks/")
            in str(task.get("include_tasks", ""))
        )

    def _task(self, word: str) -> dict:
        tasks = load_yaml_str(read_text(str(ROLES / self.ROLE / self.SUBTASKS)))
        return next(t for t in tasks if word in t["name"])

    def _holds(
        self,
        task: str,
        enforced: bool,
        state: str,
        apps: dict[str, str],
        second_factor: bool = True,
        owned: bool = False,
        switched: bool = False,
    ) -> bool:
        """Whether the ``when`` of one task of the enforcement block holds.

        Args:
            task: a word of the task's name.
            enforced: ``login.method.2fa.enforced``.
            state: the stdout of ``occ twofactorauth:enforce``.
            apps: the enabled apps ``occ app:list`` reports.
            second_factor: ``login.method.2fa.enabled``.
            owned: whether the ownership marker is set.
            switched: whether the switch task changed the enforcement.
        """
        include = self._include()
        variables = {
            "NEXTCLOUD_LOGIN_2FA": second_factor,
            "NEXTCLOUD_LOGIN_2FA_ENFORCED": enforced and second_factor,
            "NEXTCLOUD_TWOFACTOR_APP": "twofactor_totp",
            "NEXTCLOUD_TWOFACTOR_ENFORCED_FOR_ALL": ENFORCED_FOR_ALL,
            "NEXTCLOUD_TWOFACTOR_PROVIDER_APPS": ["privacyidea"],
            "nextcloud_twofactor_state": {"stdout": state + "\n"},
            "nextcloud_twofactor_apps": {
                "stdout": json.dumps({"enabled": apps, "disabled": {}})
            },
            "nextcloud_twofactor_owner": {
                "rc": 0 if owned else 1,
                "stdout": "yes\n" if owned else "",
            },
            "nextcloud_twofactor_switch": {"changed": switched},
            **{
                name: trust_as_template(value)
                for name, value in include["vars"].items()
            },
        }
        result = Templar(loader=DataLoader(), variables=variables).template(
            trust_as_template("{{ " + self._task(task)["when"] + " }}")
        )
        return result in (True, "True")

    def _switches(
        self,
        enforced: bool,
        state: str,
        apps: dict[str, str],
        second_factor: bool = True,
        owned: bool = False,
    ) -> bool:
        return self._holds(
            "Switch", enforced, state, apps, second_factor=second_factor, owned=owned
        )

    def test_the_block_runs_on_every_deploy(self) -> None:
        self.assertNotIn("when", self._include())

    def test_turning_2fa_off_after_enforcing_switches_the_own_enforcement_off(
        self,
    ) -> None:
        self.assertTrue(
            self._switches(
                False, ENFORCED_FOR_ALL, WEBAUTHN, second_factor=False, owned=True
            )
        )
        switch = self._task("Switch")["ansible.builtin.command"]["cmd"]
        self.assertIn(
            "'--on' if NEXTCLOUD_LOGIN_2FA_ENFORCED | bool else '--off'", switch
        )

    def test_turning_2fa_off_keeps_an_enforcement_the_deploy_does_not_own(
        self,
    ) -> None:
        self.assertFalse(
            self._switches(False, ENFORCED_FOR_ALL, WEBAUTHN, second_factor=False)
        )

    def test_turning_2fa_off_keeps_an_enforcement_with_exceptions(self) -> None:
        self.assertFalse(
            self._switches(
                False, ENFORCED_EXCEPT, WEBAUTHN, second_factor=False, owned=True
            )
        )

    def test_turning_2fa_off_keeps_a_group_enforcement_an_admin_chose(self) -> None:
        self.assertFalse(
            self._switches(
                False, ENFORCED_FOR_GROUP, WEBAUTHN, second_factor=False, owned=True
            )
        )
        self.assertFalse(
            self._switches(False, NOT_ENFORCED, WEBAUTHN, second_factor=False)
        )

    def test_without_any_provider_an_enforcement_is_a_lockout_and_goes(
        self,
    ) -> None:
        for apps in ({}, {"twofactor_backupcodes": "1.0.0"}):
            with self.subTest(apps=apps):
                self.assertTrue(
                    self._switches(False, ENFORCED_FOR_GROUP, apps, second_factor=False)
                )

    def test_a_totp_app_left_enabled_still_serves_an_enforcement(self) -> None:
        self.assertFalse(
            self._switches(False, ENFORCED_FOR_GROUP, TOTP, second_factor=False)
        )

    def test_a_provider_without_the_twofactor_prefix_counts(self) -> None:
        self.assertFalse(
            self._switches(False, ENFORCED_FOR_ALL, PRIVACYIDEA, second_factor=False)
        )
        self.assertIn(
            "privacyidea",
            render(
                self.ROLE,
                "{{ NEXTCLOUD_TWOFACTOR_PROVIDER_APPS }}",
                NATIVE,
                self.ENTITY,
                {},
            ),
        )

    def test_switching_the_enforcement_on_marks_it_as_the_deploys_own(self) -> None:
        self.assertTrue(self._holds("Mark", True, NOT_ENFORCED, TOTP, switched=True))
        self.assertFalse(self._holds("Mark", True, ENFORCED_FOR_ALL, TOTP))
        self.assertFalse(
            self._holds("Mark", False, ENFORCED_FOR_ALL, TOTP, switched=True)
        )

    def test_the_marker_is_released_once_the_deploy_stops_enforcing(self) -> None:
        self.assertTrue(
            self._holds(
                "Release",
                False,
                ENFORCED_EXCEPT,
                WEBAUTHN,
                second_factor=False,
                owned=True,
            )
        )
        self.assertFalse(
            self._holds("Release", True, ENFORCED_FOR_ALL, TOTP, owned=True)
        )
        self.assertFalse(
            self._holds("Release", False, NOT_ENFORCED, WEBAUTHN, second_factor=False)
        )

    def test_an_unenforced_instance_with_totp_is_switched_on(self) -> None:
        self.assertTrue(self._switches(True, NOT_ENFORCED, TOTP))

    def test_an_operators_enforcement_is_left_as_it_is(self) -> None:
        self.assertFalse(self._switches(True, ENFORCED_FOR_ALL, TOTP))
        self.assertFalse(self._switches(True, ENFORCED_FOR_GROUP, TOTP))

    def test_no_enforcement_without_the_totp_app(self) -> None:
        self.assertFalse(self._switches(True, NOT_ENFORCED, {}))

    def test_an_offered_second_factor_switches_only_the_own_enforcement_off(
        self,
    ) -> None:
        self.assertTrue(self._switches(False, ENFORCED_FOR_ALL, TOTP, owned=True))
        self.assertFalse(self._switches(False, NOT_ENFORCED, TOTP, owned=True))

    def test_an_offered_second_factor_keeps_an_admins_enforcement(self) -> None:
        for state in (ENFORCED_FOR_ALL, ENFORCED_FOR_GROUP, ENFORCED_EXCEPT):
            with self.subTest(state=state):
                self.assertFalse(self._switches(False, state, TOTP))


if __name__ == "__main__":
    unittest.main()
