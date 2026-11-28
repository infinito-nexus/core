from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from cli.administration.deploy.development.common import DEV_INVENTORY_VARS_FILE
from utils.cache import base
from utils.cache.applications import get_merged_applications
from utils.cache.reset import _reset_cache_for_tests
from utils.cache.users import get_merged_users
from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
INVENTORY = PROJECT_ROOT / DEV_INVENTORY_VARS_FILE


class TestScopedFingerprintRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        loader = DataLoader()
        scope = dict(loader.load_from_file(str(INVENTORY)))
        scope.update(
            {
                "DOMAIN_PRIMARY": default_domain_primary(),
                "ansible_facts": {"os_family": "Debian"},
                "ansible_connection": "local",
                "inventory_hostname": "localhost",
                "group_names": [],
                "RESOURCE_HOST_CPUS_OVERRIDE": 4,
                "RESOURCE_HOST_MEM_MB_OVERRIDE": 16000,
            }
        )
        cls.inventory = scope
        cls.served: list[tuple[object, str, str]] = []
        scoped = base._scoped_fingerprint

        def spy(obj):
            digest = scoped(obj)
            if (
                obj is not None
                and getattr(base._RENDER_GUARD, "fingerprints", None) is not None
            ):
                cls.served.append((obj, digest, base._fingerprint_mapping(obj)))
            return digest

        _reset_cache_for_tests()
        with mock.patch.object(base, "_scoped_fingerprint", side_effect=spy):
            cls.applications = get_merged_applications(
                variables=scope,
                roles_dir=str(ROLES_DIR),
                templar=Templar(loader=loader, variables=scope),
            )
            cls.users = get_merged_users(
                variables=scope,
                roles_dir=str(ROLES_DIR),
                templar=Templar(loader=loader, variables=scope),
            )

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_the_render_keys_its_nested_lookups_inside_a_scope(self) -> None:
        self.assertTrue(self.applications)
        self.assertTrue(self.users)
        self.assertGreater(len(self.served), 1)

    def test_every_in_scope_key_is_a_fresh_fingerprint_of_the_same_object(
        self,
    ) -> None:
        stale = [
            index
            for index, (_, served, fresh) in enumerate(self.served)
            if served != fresh
        ]
        self.assertEqual([], stale)

    def test_the_scope_holds_the_inventory_mappings_themselves(self) -> None:
        held = {id(obj) for obj, _, _ in self.served}
        inventory = {
            id(self.inventory["applications"]),
            id(self.inventory["users"]),
        }
        self.assertTrue(held)
        self.assertLessEqual(held, inventory)


if __name__ == "__main__":
    unittest.main()
