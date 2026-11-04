import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.preflight.switches import PREFLIGHT_ROLE, check_enabled
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _switch(check: str, enabled: str) -> str:
    return f"preflight:\n  checks:\n    {check}:\n      enabled: {enabled}\n"


class TestCheckEnabled(unittest.TestCase):
    def _roles(self, services: str) -> Path:
        tmp = tempfile.TemporaryDirectory(prefix="preflight-switches-")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / PREFLIGHT_ROLE / ROLE_FILE_META_SERVICES
        path.parent.mkdir(parents=True)
        path.write_text(services, encoding="utf-8")
        return Path(tmp.name)

    def test_the_shipped_inventory_check_is_on(self):
        roles = Path(PROJECT_ROOT) / "roles"
        self.assertIs(check_enabled("inventory", roles), True)

    def test_a_switch_set_to_false_reads_false(self):
        roles = self._roles(_switch("inventory", "false"))
        self.assertIs(check_enabled("inventory", roles), False)

    def test_a_check_the_role_does_not_declare_is_rejected(self):
        roles = self._roles(_switch("ports", "true"))
        with self.assertRaisesRegex(ValueError, "checks.inventory.enabled"):
            check_enabled("inventory", roles)

    def test_a_jinja_switch_is_rejected(self):
        roles = self._roles(_switch("inventory", "\"{{ 'x' in group_names }}\""))
        with self.assertRaisesRegex(TypeError, "must be true or false"):
            check_enabled("inventory", roles)

    def test_a_roles_tree_without_the_role_is_rejected(self):
        with (
            tempfile.TemporaryDirectory() as empty,
            self.assertRaises(FileNotFoundError),
        ):
            check_enabled("inventory", Path(empty))


if __name__ == "__main__":
    unittest.main()
