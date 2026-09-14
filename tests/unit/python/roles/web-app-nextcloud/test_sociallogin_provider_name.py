from __future__ import annotations

import unittest

from jinja2 import Environment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

ADDON = PROJECT_ROOT / "roles/web-app-nextcloud/meta/addons/sociallogin.yml"
UID_LIMIT = 64
KEYCLOAK_SUB_LENGTH = 36


def _provider_name_call() -> tuple:
    config = load_yaml_str(read_text(str(ADDON)))["config"]["plugin_configuration"]
    providers = next(
        entry["configvalue"]
        for entry in config
        if entry["configkey"] == "custom_providers"
    )
    calls = []

    def lookup(*args):
        calls.append(args)
        return ""

    Environment(autoescape=True).from_string(
        providers["custom_oidc"][0]["name"]
    ).render(lookup=lookup)
    return calls[0]


class TestSocialLoginProviderName(unittest.TestCase):
    def test_the_provider_name_leaves_room_for_the_keycloak_sub(self) -> None:
        kind, application_id, max_length = _provider_name_call()
        self.assertEqual((kind, application_id), ("bounded_name", "web-app-keycloak"))
        self.assertLessEqual(
            max_length + 1 + KEYCLOAK_SUB_LENGTH,
            UID_LIMIT,
            'Nextcloud rejects a sociallogin uid ("<name>-<sub>") over 64 chars',
        )


if __name__ == "__main__":
    unittest.main()
