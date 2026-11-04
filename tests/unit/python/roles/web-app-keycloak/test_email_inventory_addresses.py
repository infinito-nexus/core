import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_VARS = load_yaml_any(
    str(PROJECT_ROOT / "roles/web-app-keycloak" / ROLE_FILE_VARS_MAIN)
)
USERS = {
    "biber": {
        "username": "biber",
        "email": "biber@example.com",
        "secondary_email": "biber@example.org",
    },
    "castor": {
        "username": "castor",
        "email": "castor@example.com",
        "secondary_email": "",
    },
}


def addresses(mailbox: bool) -> str:
    """Render the addresses email_verified.py stamps for a policy.

    Args:
        mailbox: True under the mailbox policy.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    env.filters["dict2items"] = lambda mapping: [
        {"key": key, "value": value} for key, value in mapping.items()
    ]
    env.filters["items2dict"] = lambda items, key_name, value_name: {
        item[key_name]: item[value_name] for item in items
    }
    key = env.from_string(ROLE_VARS["KEYCLOAK_EMAIL_INVENTORY_KEY"]).render(
        KEYCLOAK_EMAIL_MAILBOX=mailbox
    )
    return env.from_string(ROLE_VARS["KEYCLOAK_EMAIL_INVENTORY_ADDRESSES"]).render(
        lookup=lambda name: USERS, KEYCLOAK_EMAIL_INVENTORY_KEY=key
    )


class TestEmailInventoryAddresses(unittest.TestCase):
    def test_the_mailbox_policy_stamps_the_secondary_address(self):
        self.assertEqual(
            addresses(True), "{'biber': 'biber@example.org', 'castor': ''}"
        )

    def test_the_external_policy_stamps_the_primary_address(self):
        self.assertEqual(
            addresses(False),
            "{'biber': 'biber@example.com', 'castor': 'castor@example.com'}",
        )


if __name__ == "__main__":
    unittest.main()
