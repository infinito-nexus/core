"""The fields plg_system_keycloak locks are the fields the lock renderer decorates.

``Keycloak.php`` locks ``MANAGED_FIELDS`` plus every mapped ``plg_user_profile``
key and marks them ``data-infinito-sso-locked``; ``services.sso.profile.locked``
names the inputs the shared renderer decorates. Both lists must name the same
form fields, so neither can gain or lose one alone.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles/web-app-joomla"
PLUGIN = (
    ROLE / "files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php"
)
ADDON = ROLE / "meta/addons/plg_system_keycloak.yml"
SERVICES = ROLE / ROLE_FILE_META_SERVICES
MARKER = "data-infinito-sso-locked"
BLOCK = re.compile(r"MANAGED_FIELDS = \[(.*?)\];", re.DOTALL)
PAIR = re.compile(r"\['(\w+)',\s*(?:null|'(\w+)')\]")
SELECTOR_ID = re.compile(r"#(jform_\w+)\[" + re.escape(MARKER) + r"\]")


def _locked_by_the_plugin() -> set[str]:
    block = BLOCK.search(read_text(str(PLUGIN))).group(1)
    pairs = [(field, group or None) for field, group in PAIR.findall(block)]
    profile = load_yaml_any(ADDON)["config"]["profile"]
    pairs += [(key, "profile") for key in [*profile["claims"], *profile["address"]]]
    return {
        f"jform_{group}_{field}" if group else f"jform_{field}"
        for field, group in pairs
    }


def _decorated_by_the_renderer() -> set[str]:
    locked = load_yaml_any(SERVICES)["sso"]["profile"]["locked"]
    return {
        match for selector in locked.values() for match in SELECTOR_ID.findall(selector)
    }


class TestProfileLockFields(unittest.TestCase):
    def test_the_plugin_and_the_renderer_lock_the_same_fields(self):
        self.assertEqual(_locked_by_the_plugin(), _decorated_by_the_renderer())

    def test_name_username_and_email_are_locked(self):
        self.assertLessEqual(
            {"jform_name", "jform_username", "jform_email1"}, _locked_by_the_plugin()
        )

    def test_every_selector_matches_only_marked_fields(self):
        locked = load_yaml_any(SERVICES)["sso"]["profile"]["locked"]
        unmarked = [
            part.strip()
            for selector in locked.values()
            for part in selector.split(",")
            if not SELECTOR_ID.fullmatch(part.strip())
        ]
        self.assertEqual([], unmarked)


if __name__ == "__main__":
    unittest.main()
