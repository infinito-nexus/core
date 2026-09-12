"""Guard the Mailu→Stalwart migration coupling.

The migration e2e (`roles/web-app-stalwart/files/test/test.sh`) only runs when
`web-app-mailu` is pulled into the deploy round, which happens through the
`mailu` service key of `web-app-stalwart`. Two invariants keep that wiring
honest, and both fail loudly instead of silently skipping the scenario:

* the legacy provider must not be end-of-life while the migration path is
  still exercised — once `web-app-mailu` is declared `lifecycle: eol` the
  variant flag must be switched off and the migration path retired;
* the switch the role reads (`services.stalwart.migration.import_mailu`) must
  stay declared and default to off, so a normal deploy never imports.
"""

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

_STALWART = "web-app-stalwart"
_MAILU = "web-app-mailu"
_ROLES = PROJECT_ROOT / "roles"


def _services(role: str) -> dict:
    return load_yaml_any(_ROLES / role / ROLE_FILE_META_SERVICES) or {}


def _variants(role: str) -> list:
    path = _ROLES / role / ROLE_FILE_META_VARIANTS
    return load_yaml_any(path, default_if_missing=[]) or []


def _mailu_flag_in_variants() -> list[bool]:
    flags = []
    for variant in _variants(_STALWART):
        services = (variant or {}).get("services") or {}
        entry = services.get("mailu")
        if isinstance(entry, dict) and "enabled" in entry:
            flags.append(bool(entry["enabled"]))
    return flags


class MailMigrationGateTests(unittest.TestCase):
    def test_the_migration_variant_pulls_the_legacy_provider_in(self) -> None:
        self.assertIn(
            True,
            _mailu_flag_in_variants(),
            f"No {_STALWART} variant enables the 'mailu' service key, so the "
            "migration e2e would never run. Re-enable it or delete the scenario.",
        )

    def test_the_legacy_provider_is_not_eol_while_the_migration_runs(self) -> None:
        lifecycles = {
            str(entry.get("lifecycle"))
            for entry in _services(_MAILU).values()
            if isinstance(entry, dict) and entry.get("lifecycle")
        }
        if True not in _mailu_flag_in_variants():
            self.skipTest("migration variant already retired")
        self.assertNotIn(
            "eol",
            lifecycles,
            f"{_MAILU} is end-of-life but {_STALWART} still co-deploys it for the "
            "migration scenario. Set the variant's services.mailu.enabled to false "
            "and drop the migration path.",
        )

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
