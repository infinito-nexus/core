"""An inventory override of one login method reaches the application's switch.

Every render goes through the role's real ``vars/main.yml`` and the real
``config`` lookup, with the override in ``applications`` the way an inventory
sets it, and the deployed roles in ``group_names`` picking the mode.

The merged applications payload skips its eager render of every application:
that render costs seconds per inventory, and the ``config`` lookup renders the
one value it returns itself. The module drops the payloads it cached that way.
"""

from __future__ import annotations

import json
import re
import unittest
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from tests.lint.ansible.services import test_login_methods as lint
from utils.cache import applications as applications_cache
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.reset import _reset_cache_for_tests
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from collections.abc import Mapping

ROLES = PROJECT_ROOT / "roles"
SSO = ("web-app-keycloak", "svc-db-openldap")
LDAP = ("svc-db-openldap",)
NATIVE = ()


def _unrendered(value: Any, **_context: Any) -> Any:
    return value


_EAGER_RENDER = mock.patch.object(
    applications_cache, "_render_with_templar", new=_unrendered
)


def setUpModule() -> None:
    _reset_cache_for_tests()
    _EAGER_RENDER.start()


def tearDownModule() -> None:
    _EAGER_RENDER.stop()
    _reset_cache_for_tests()


def render(
    role: str,
    template: str,
    mode: tuple[str, ...],
    flags: Mapping[str, Mapping[str, bool]],
    extra: Mapping[str, Any],
) -> Any:
    """Render *template* in *role*'s variable scope.

    Args:
        role: the application whose ``vars/main.yml`` is in scope.
        template: Jinja text.
        mode: the roles deployed next to *role*.
        flags: inventory overrides as ``{role: {entity.method: enabled}}``.
        extra: further variables the template reads from outside the role.
    """
    applications: dict[str, Any] = {}
    for owner, methods in flags.items():
        for dotted, enabled in methods.items():
            entity, method = dotted.split(".")
            login = (
                applications.setdefault(owner, {})
                .setdefault("services", {})
                .setdefault(entity, {})
                .setdefault("login", {"method": {}})
            )
            login["method"][method] = {"enabled": enabled}
    loader = DataLoader()
    variables = {
        **loader.load_from_file(
            str(ROLES / role / ROLE_FILE_VARS_MAIN), trusted_as_template=True
        ),
        **extra,
        "group_names": sorted({role, *mode}),
        "applications": applications,
        "playbook_dir": str(PROJECT_ROOT),
    }
    return Templar(loader=loader, variables=variables).template(
        trust_as_template(template)
    )


def template_line(role: str, relative: str, prefix: str) -> str:
    """The one line of a role template that starts with *prefix*.

    Args:
        role: the role that ships the template.
        relative: the template's path below the role.
        prefix: the line's start, such as ``NAME=``.
    """
    lines = [
        line
        for line in read_text(str(ROLES / role / relative)).splitlines()
        if line.startswith(prefix)
    ]
    if len(lines) != 1:
        raise AssertionError(f"{role}/{relative}: {len(lines)} lines start {prefix!r}")
    return lines[0]


class TestEnvironmentSwitchPenpot(unittest.TestCase):
    ROLE = "web-app-penpot"

    def _flags(self, mode: tuple[str, ...], **methods: bool) -> list[str]:
        line = template_line(self.ROLE, "templates/env.j2", "PENPOT_FLAGS=")
        flags = {self.ROLE: {f"penpot.{m}": v for m, v in methods.items()}}
        return render(self.ROLE, line, mode, flags, {}).split("=", 1)[1].split()

    def test_sso_mode_disables_the_password_login(self) -> None:
        self.assertIn("disable-login-with-password", self._flags(SSO))

    def test_a_native_override_enables_the_password_login(self) -> None:
        self.assertIn("enable-login-with-password", self._flags(SSO, native=True))

    def test_a_registration_override_enables_registration(self) -> None:
        self.assertIn("enable-registration", self._flags(SSO, registration=True))

    def test_an_sso_override_drops_the_oidc_login(self) -> None:
        self.assertNotIn("enable-login-with-oidc", self._flags(SSO, sso=False))

    def test_ldap_mode_offers_the_ldap_login_only(self) -> None:
        self.assertEqual(
            {"enable-login-with-ldap", "disable-login-with-password"},
            {flag for flag in self._flags(LDAP) if "login-with" in flag},
        )


class TestEnvironmentSwitchMobilizon(unittest.TestCase):
    ROLE = "web-app-mobilizon"

    def _value(self, name: str, mode: tuple[str, ...], **methods: bool) -> str:
        line = template_line(self.ROLE, "templates/env.j2", f"{name}=")
        flags = {self.ROLE: {f"mobilizon.{m}": v for m, v in methods.items()}}
        return render(self.ROLE, line, mode, flags, {}).split("=", 1)[1]

    def test_sso_mode_disables_the_database_login(self) -> None:
        self.assertEqual(
            "true", self._value("MOBILIZON_INSTANCE_DISABLE_DATABASE_LOGIN", SSO)
        )

    def test_a_native_override_enables_the_database_login(self) -> None:
        self.assertEqual(
            "false",
            self._value("MOBILIZON_INSTANCE_DISABLE_DATABASE_LOGIN", SSO, native=True),
        )

    def test_native_mode_enables_the_database_login(self) -> None:
        self.assertEqual(
            "false", self._value("MOBILIZON_INSTANCE_DISABLE_DATABASE_LOGIN", NATIVE)
        )

    def test_a_registration_override_opens_registrations(self) -> None:
        self.assertEqual(
            "true",
            self._value(
                "MOBILIZON_INSTANCE_REGISTRATIONS_OPEN", NATIVE, registration=True
            ),
        )


class TestConfigFileSwitchTaiga(unittest.TestCase):
    ROLE = "web-app-taiga"

    def _conf(self, mode: tuple[str, ...], **methods: bool) -> dict[str, Any]:
        template = read_text(str(ROLES / self.ROLE / "templates/settings/conf.json.j2"))
        flags = {self.ROLE: {f"taiga.{m}": v for m, v in methods.items()}}
        rendered = render(
            self.ROLE, template, mode, flags, {"OIDC": {"BUTTON_TEXT": "Sign in"}}
        )
        return rendered if isinstance(rendered, dict) else json.loads(rendered)

    def test_sso_mode_hides_the_login_form(self) -> None:
        self.assertIs(False, self._conf(SSO)["defaultLoginEnabled"])

    def test_a_native_override_shows_the_login_form(self) -> None:
        self.assertIs(True, self._conf(SSO, native=True)["defaultLoginEnabled"])

    def test_a_registration_override_opens_the_public_register(self) -> None:
        self.assertIs(True, self._conf(SSO, registration=True)["publicRegisterEnabled"])

    def test_an_sso_override_drops_the_oidc_plugin(self) -> None:
        self.assertNotIn(
            "/plugins/oidc-auth/oidc-auth.json",
            self._conf(SSO, sso=False)["contribPlugins"],
        )

    def test_ldap_mode_keeps_the_form_for_ldap(self) -> None:
        conf = self._conf(LDAP)
        self.assertEqual(
            (True, "ldap"), (conf["defaultLoginEnabled"], conf["loginFormType"])
        )

    def test_an_ldap_override_drops_the_ldap_form_type(self) -> None:
        self.assertNotIn("loginFormType", self._conf(LDAP, ldap=False))


class TestDatabaseSettingSwitchDiscourse(unittest.TestCase):
    ROLE = "web-app-discourse"
    TASK = "⚙️ Apply and read back the site settings and the administrator password"
    SETTINGS: ClassVar[dict[str, str]] = {
        "enable_local_logins": "DISCOURSE_LOCAL_LOGINS",
        "enable_local_logins_via_email": "DISCOURSE_LOGIN_EMAIL",
        "enable_passkeys": "DISCOURSE_LOGIN_PASSKEY",
        "allow_new_registrations": "DISCOURSE_ALLOW_NEW_REGISTRATIONS",
    }
    templates: ClassVar[dict[str, str]]

    @classmethod
    def setUpClass(cls) -> None:
        tasks = DataLoader().load_from_file(
            str(ROLES / cls.ROLE / "tasks/stack_host/02_credentials.yml"),
            trusted_as_template=True,
        )
        task = next(task for task in tasks if task["name"] == cls.TASK)
        cls.templates = {
            name: f"{name}={value}"
            for name, value in re.findall(
                r"-e ([A-Z_]+)=(\{\{.*?\}\})", str(task["ansible.builtin.shell"]["cmd"])
            )
        }
        cls.templates.update(
            {name: f"{name}={value}" for name, value in task["environment"].items()}
        )

    def _value(self, name: str, mode: tuple[str, ...], **methods: bool) -> str:
        flags = {self.ROLE: {f"discourse.{m}": v for m, v in methods.items()}}
        return render(self.ROLE, self.templates[name], mode, flags, {}).split("=", 1)[1]

    def test_sso_mode_turns_the_local_logins_off(self) -> None:
        self.assertEqual("false", self._value("DISCOURSE_LOCAL_LOGINS", SSO))

    def test_a_native_override_turns_the_local_logins_on(self) -> None:
        self.assertEqual(
            "true", self._value("DISCOURSE_LOCAL_LOGINS", SSO, native=True)
        )

    def test_native_mode_turns_the_local_logins_on(self) -> None:
        self.assertEqual("true", self._value("DISCOURSE_LOCAL_LOGINS", NATIVE))

    def test_a_passkey_override_turns_the_passkeys_on(self) -> None:
        self.assertEqual(
            "true", self._value("DISCOURSE_LOGIN_PASSKEY", SSO, passkey=True)
        )

    def test_an_email_override_turns_the_magic_link_on(self) -> None:
        self.assertEqual(
            "true", self._value("DISCOURSE_LOGIN_EMAIL", NATIVE, email=True)
        )

    def test_native_mode_keeps_registrations_closed(self) -> None:
        self.assertEqual(
            "false", self._value("DISCOURSE_ALLOW_NEW_REGISTRATIONS", NATIVE)
        )

    def test_a_registration_override_opens_registrations(self) -> None:
        self.assertEqual(
            "true",
            self._value("DISCOURSE_ALLOW_NEW_REGISTRATIONS", NATIVE, registration=True),
        )

    def test_the_console_stores_each_value_as_its_site_setting(self) -> None:
        script = read_text(str(ROLES / self.ROLE / "files/ruby/apply_settings.rb"))
        for setting, name in self.SETTINGS.items():
            with self.subTest(setting=setting):
                self.assertIn(
                    f'SiteSetting.{setting} = ENV.fetch("{name}") == "true"', script
                )


class TestInjectedScriptSwitchPixelfed(unittest.TestCase):
    ROLE = "web-app-pixelfed"
    FORM = 'form[action$="/login"]'
    TWO_FACTOR = "/settings/security/2fa/setup"

    def _script(self, mode: tuple[str, ...], **methods: bool) -> str:
        template = read_text(str(ROLES / self.ROLE / "templates/javascript.js.j2"))
        flags = {self.ROLE: {f"pixelfed.{m}": v for m, v in methods.items()}}
        return render(self.ROLE, template, mode, flags, {})

    def _injected(self, mode: tuple[str, ...], **methods: bool) -> bool:
        flags = {self.ROLE: {f"pixelfed.{m}": v for m, v in methods.items()}}
        expression = f"{{{{ lookup('config', '{self.ROLE}', 'services.javascript.enabled') | bool }}}}"
        return render(self.ROLE, expression, mode, flags, {})

    def test_sso_mode_hides_the_local_form(self) -> None:
        self.assertIn(self.FORM, self._script(SSO))

    def test_a_native_override_keeps_the_local_form(self) -> None:
        self.assertNotIn(self.FORM, self._script(SSO, native=True))

    def test_sso_mode_hides_the_second_factor_setup(self) -> None:
        self.assertIn(self.TWO_FACTOR, self._script(SSO))

    def test_a_2fa_override_keeps_the_second_factor_setup(self) -> None:
        self.assertNotIn(self.TWO_FACTOR, self._script(SSO, **{"2fa": True}))

    def test_sso_mode_injects_the_script(self) -> None:
        self.assertIs(True, self._injected(SSO))

    def test_native_mode_hides_nothing(self) -> None:
        script = self._script(NATIVE)
        self.assertNotIn(self.FORM, script)
        self.assertNotIn(self.TWO_FACTOR, script)


class TestExtrasStayOffInEveryMode(unittest.TestCase):
    MODES: ClassVar[dict[str, tuple[str, ...]]] = {
        "sso": SSO,
        "ldap": LDAP,
        "native": NATIVE,
    }

    def _gitea_openid(self, mode: tuple[str, ...], **methods: bool) -> str:
        role = "web-app-gitea"
        line = template_line(
            role, "templates/env.j2", "GITEA__openid__ENABLE_OPENID_SIGNIN="
        )
        flags = {role: {f"gitea.{m}": v for m, v in methods.items()}}
        return render(role, line, mode, flags, {}).split("=", 1)[1]

    def _odoo_hides_passkey(self, mode: tuple[str, ...], **methods: bool) -> str:
        role = "web-app-odoo"
        line = template_line(
            role, "templates/javascript.js.j2", "  const hidePasskey ="
        )
        flags = {role: {f"odoo.{m}": v for m, v in methods.items()}}
        return render(role, line, mode, flags, {}).split("=", 1)[1].strip(" ;")

    def test_gitea_offers_no_openid2_sign_in(self) -> None:
        for name, mode in self.MODES.items():
            with self.subTest(mode=name):
                self.assertEqual("false", self._gitea_openid(mode))

    def test_an_openid2_override_enables_the_gitea_sign_in(self) -> None:
        self.assertEqual("true", self._gitea_openid(NATIVE, openid2=True))

    def test_odoo_hides_its_passkey_entry(self) -> None:
        for name, mode in self.MODES.items():
            with self.subTest(mode=name):
                self.assertEqual("true", self._odoo_hides_passkey(mode))

    def test_a_passkey_override_shows_the_odoo_passkey_entry(self) -> None:
        self.assertEqual("false", self._odoo_hides_passkey(NATIVE, passkey=True))


class TestEveryRoleVariableFollowsItsOverride(unittest.TestCase):
    """Each ``vars/main.yml`` variable that reads a flag renders the override.

    With SSO and LDAP on, the default turns ``sso`` on and every other method
    off; the flipped inventory inverts every declared flag of every role at
    once, so one render per polarity covers all of them. ``PINNED_OFF`` names
    the variables a role gates on a service it pins off, which stay off.
    """

    PINNED_OFF: ClassVar[dict[tuple[str, str], str]] = {
        (
            "web-app-xwiki",
            "XWIKI_LOGIN_LDAP",
        ): "meta/services.yml pins services.ldap.enabled to false, so the ldap "
        "method takes effect only with services.ldap.enabled overridden as well",
    }
    readers: ClassVar[list[tuple[str, str, str]]]
    flipped: ClassVar[dict[str, dict[str, bool]]]
    roles: ClassVar[tuple[str, ...]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.readers = []
        cls.flipped = {}
        for role, entity, method in lint.declared_flags():
            cls.flipped.setdefault(role, {})[f"{entity}.{method}"] = method != "sso"
            key = lint.flag_key(entity, method)
            cls.readers.extend(
                (role, method, str(name))
                for name, value in lint.role_variables(role).items()
                if key in str(value)
            )
        cls.roles = tuple(sorted(cls.flipped))

    def _value(
        self, role: str, name: str, flags: Mapping[str, Mapping[str, bool]]
    ) -> Any:
        return render(role, f"{{{{ {name} }}}}", (*SSO, *self.roles), flags, {})

    def _expected(self, role: str, method: str, name: str, flipped: bool) -> bool:
        return (role, name) not in self.PINNED_OFF and (method == "sso") != flipped

    def test_the_scan_finds_readers(self) -> None:
        self.assertNotEqual([], self.readers)

    def test_every_pinned_variable_is_a_reader(self) -> None:
        readers = {(role, name) for role, _, name in self.readers}
        self.assertEqual(set(), set(self.PINNED_OFF) - readers)

    def test_the_defaults_follow_the_sso_mode(self) -> None:
        for role, method, name in self.readers:
            with self.subTest(role=role, variable=name):
                self.assertIs(
                    self._expected(role, method, name, flipped=False),
                    self._value(role, name, {}),
                )

    def test_the_flipped_inventory_reaches_every_variable(self) -> None:
        for role, method, name in self.readers:
            with self.subTest(role=role, variable=name):
                self.assertIs(
                    self._expected(role, method, name, flipped=True),
                    self._value(role, name, self.flipped),
                )


if __name__ == "__main__":
    unittest.main()
