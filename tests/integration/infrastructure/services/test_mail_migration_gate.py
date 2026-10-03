"""Guard the Mailu→Stalwart import switch.

`web-app-mailu` is deprecated, so CI no longer co-deploys it and the import has
no e2e run. The switch the role reads (`services.stalwart.migration.import_mailu`)
must still stay declared and default to off, so a normal deploy never imports.
"""

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_STALWART = "web-app-stalwart"
_ROLES = PROJECT_ROOT / "roles"


def _services(role: str) -> dict:
    return load_yaml_any(_ROLES / role / ROLE_FILE_META_SERVICES) or {}


class MailMigrationGateTests(unittest.TestCase):
    def test_the_import_switch_is_declared_and_defaults_off(self) -> None:
        stalwart = _services(_STALWART).get("stalwart") or {}
        migration = stalwart.get("migration")
        self.assertIsInstance(
            migration,
            dict,
            f"{_STALWART} must declare services.stalwart.migration.",
        )
        self.assertIs(
            migration.get("import_mailu"),
            False,
            "import_mailu must default to false — a normal deploy must never "
            "import legacy mailboxes.",
        )


if __name__ == "__main__":
    unittest.main()
