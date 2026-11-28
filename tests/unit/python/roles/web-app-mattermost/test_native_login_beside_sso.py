from __future__ import annotations

import unittest
import unittest.mock as mock

from jinja2.nativetypes import NativeEnvironment

from plugins.lookup.login_method import LookupModule
from tests.lint.ansible.services import test_login_methods as lint
from utils.cache.yaml import load_yaml_any
from utils.meta.scan import ROLES_DIR
from utils.roles.mapping import ROLE_FILE_META_SERVICES

MATTERMOST = "web-app-mattermost"


class _SsoOn:
    def run(self, terms, variables=None):
        return [terms[1] == "services.sso.enabled"]


def _login_method(_name: str, application_id: str, method: str) -> object:
    module = LookupModule()
    module._templar = None
    module._loader = None
    with mock.patch(
        "plugins.lookup.login_method.lookup_loader.get", return_value=_SsoOn()
    ):
        return module.run([application_id, method], variables={})[0]


def native_with_sso_on(role: str, entity: str) -> object:
    """
    Args:
        role: a role that declares ``<entity>.login.method.native``.
        entity: that entity.

    Returns:
        The role's ``native`` default rendered with ``services.sso.enabled`` on.
    """
    services = load_yaml_any(str(ROLES_DIR / role / ROLE_FILE_META_SERVICES))
    raw = services[entity]["login"]["method"]["native"]["enabled"]
    environment = NativeEnvironment()
    environment.globals["lookup"] = _login_method
    return environment.from_string(str(raw)).render()


class TestNativeLoginBesideSso(unittest.TestCase):
    def test_mattermost_keeps_its_native_form(self) -> None:
        self.assertIs(True, native_with_sso_on(MATTERMOST, "mattermost"))

    def test_every_other_role_drops_its_native_form(self) -> None:
        others = {
            role: native_with_sso_on(role, entity)
            for role, entity, method in lint.declared_flags()
            if method == "native" and role != MATTERMOST
        }
        self.assertNotEqual({}, others)
        self.assertEqual(
            {}, {role: on for role, on in others.items() if on is not False}
        )


if __name__ == "__main__":
    unittest.main()
