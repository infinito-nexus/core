from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles" / "web-app-openproject"
ENV = ROLE / "templates" / "env.j2"
SECRETS = ROLE / "meta" / "secrets.yml"

CREDENTIAL = re.compile(
    r"\{\{ lookup\('config', application_id, "
    r"'secrets\.credentials\.(?P<name>\w+)'\) \}\}"
)


def seed_settings(text: str) -> dict[str, str]:
    """
    Args:
        text: the env template source.

    Returns:
        The setting name both env spellings resolve to, mapped to its raw
        value.
    """
    found = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        name = key.strip().removeprefix("OPENPROJECT_").replace("__", "_").lower()
        if sep and name.startswith("seed_admin_user_"):
            found[name] = value.strip()
    return found


class TestSeedAdmin(unittest.TestCase):
    def setUp(self):
        self.settings = seed_settings(read_text(str(ENV)))

    def test_no_seeder_run_locks_an_admin(self):
        self.assertEqual(
            self.settings.get("seed_admin_user_locked", "false"),
            "false",
            "every seeder run, also a compose restart by sys-ctl-rpr-container-soft, "
            "locks the lowest-id admin, which is the platform administrator once the "
            "role demotes the seeded one",
        )

    def test_the_seeded_admin_never_gets_the_published_password(self):
        match = CREDENTIAL.fullmatch(self.settings.get("seed_admin_user_password", ""))
        self.assertIsNotNone(
            match,
            "without a stored credential the seeder creates admin with the published "
            "password admin",
        )
        declared = load_yaml_any(str(SECRETS))["credentials"]
        self.assertEqual(declared[match["name"]]["algorithm"], "sha256")

    def test_the_checks_catch_a_lock_and_the_published_password(self):
        planted = seed_settings(
            "OPENPROJECT_SEED_ADMIN_USER_LOCKED=true\n"
            "OPENPROJECT_SEED__ADMIN__USER__PASSWORD=admin\n"
        )
        self.assertEqual(planted["seed_admin_user_locked"], "true")
        self.assertIsNone(CREDENTIAL.fullmatch(planted["seed_admin_user_password"]))


if __name__ == "__main__":
    unittest.main()
