import itertools
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/web-app-penpot"


def rendered_flags(sso: bool, ldap: bool) -> str:
    names = load_yaml(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    return (
        env.from_string(names["PENPOT_FLAGS"])
        .render(
            PENPOT_SSO_ENABLED=sso,
            PENPOT_LDAP_ENABLED=ldap,
            PENPOT_REGISTRATION_ENABLED=sso,
            PENPOT_NATIVE_LOGIN_ENABLED=not sso,
        )
        .strip()
    )


class TestAdminConsoleFlag(unittest.TestCase):
    def test_every_login_mode_opts_out_of_the_undeployed_admin_console(self):
        for sso, ldap in itertools.product((True, False), repeat=2):
            with self.subTest(sso=sso, ldap=ldap):
                flags = rendered_flags(sso, ldap)
                self.assertIn(" disable-admin-console ", f" {flags} ")
                self.assertNotIn("enable-admin-console", flags.split())


if __name__ == "__main__":
    unittest.main()
