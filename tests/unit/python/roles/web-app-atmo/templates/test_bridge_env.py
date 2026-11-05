"""The bridge signs in to Mobilizon as its own account, never as the platform administrator."""

import unittest
from pathlib import PurePosixPath

from jinja2 import DictLoader, Environment, StrictUndefined

from cli.administration.inventory.provision.users_generator import (
    required_user_policies,
)
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_USERS, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLES = PROJECT_ROOT / "roles"
ROLE = ROLES / "web-app-atmo"
TEMPLATE = "roles/web-app-atmo/templates/env/bridge.j2"
INCLUDE = "roles/sys-svc-container/templates/env.j2"
BRIDGE_ACCOUNT = "web-app-mobilizon-atmo-bridge"
PLATFORM_ADMIN = "platform_administrator"
VARIABLES = {
    "HOST_TIMEZONE": "UTC",
    "ATMO_PDS_URL": "https://api.bluesky.example.org",
    "ATMO_PUBLIC_URL": "https://rsvp.example.org",
    "ATMO_MOBILIZON_URL": "https://event.example.org",
    "ATMO_BRIDGE_STATE_DIR": "/var/lib/atmo-bridge",
    "ATMO_BRIDGE_INTERVAL_SECONDS": "60",
}


def _user(key: str) -> dict:
    return {"email": f"{key}@example.org", "password": f"secret-of-{key}"}


def _environment(template_text: str) -> Environment:
    environment = Environment(
        loader=DictLoader(
            {INCLUDE: read_text(str(PROJECT_ROOT / INCLUDE)), TEMPLATE: template_text}
        ),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - renders a dotenv file, not markup
    )
    environment.globals["lookup"] = lambda name, key: _user(key)
    environment.filters["dotenv_quote"] = str
    environment.filters["path_join"] = lambda parts: str(PurePosixPath(*parts))
    return environment


def render(template_text: str) -> dict[str, str]:
    """Render the bridge env file with the role's own account variable.

    Args:
        template_text: the template source to render.

    Returns:
        The rendered ``KEY=value`` pairs.
    """
    environment = _environment(template_text)
    account_expression = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))[
        "ATMO_BRIDGE_ACCOUNT"
    ].strip()[2:-2]
    account = environment.compile_expression(account_expression)()
    rendered = environment.get_template(TEMPLATE).render(
        **VARIABLES, ATMO_BRIDGE_ACCOUNT=account
    )
    return dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)


def admin_credentials(env: dict[str, str]) -> list[str]:
    """The env keys whose value is a credential of the platform administrator.

    Args:
        env: rendered ``KEY=value`` pairs.
    """
    admin = _user(PLATFORM_ADMIN)
    return sorted(key for key, value in env.items() if value in admin.values())


class TestBridgeIdentity(unittest.TestCase):
    def setUp(self):
        self.text = read_text(str(PROJECT_ROOT / TEMPLATE))

    def test_the_bridge_signs_in_as_its_own_account(self):
        env = render(self.text)
        self.assertEqual(env["BRIDGE_MOBILIZON_EMAIL"], _user(BRIDGE_ACCOUNT)["email"])
        self.assertEqual(
            env["BRIDGE_MOBILIZON_PASSWORD"], _user(BRIDGE_ACCOUNT)["password"]
        )
        self.assertEqual(admin_credentials(env), [])

    def test_the_former_administrator_sign_in_is_reported(self):
        regressed = self.text.replace(
            "ATMO_BRIDGE_ACCOUNT.", f"lookup('users', '{PLATFORM_ADMIN}')."
        )
        self.assertEqual(
            admin_credentials(render(regressed)),
            ["BRIDGE_MOBILIZON_EMAIL", "BRIDGE_MOBILIZON_PASSWORD"],
        )

    def test_the_role_declares_the_account_and_not_the_administrator(self):
        users = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_USERS)))
        self.assertIn(BRIDGE_ACCOUNT, users)
        self.assertNotIn(PLATFORM_ADMIN, users)

    def test_the_inventory_pins_the_account_its_own_password(self):
        for application_ids in (["web-app-atmo"], ["web-app-mobilizon"]):
            with self.subTest(application_ids=application_ids):
                self.assertIn(
                    BRIDGE_ACCOUNT, required_user_policies(ROLES, application_ids)
                )
        self.assertNotIn(
            BRIDGE_ACCOUNT, required_user_policies(ROLES, ["web-app-matomo"])
        )


if __name__ == "__main__":
    unittest.main()
