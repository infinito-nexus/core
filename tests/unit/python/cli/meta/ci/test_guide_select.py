from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cli.meta.ci import guide_select
from utils.cache.files import PROJECT_ROOT
from utils.roles.mapping import ROLE_FILE_META_TESTS
from utils.roles.meta_lookup import MetaServicesShapeError, get_role_test_skips


class GuideModeTests(unittest.TestCase):
    def test_role_without_stack_deploys_in_host_mode(self):
        self.assertEqual(
            guide_select._guide_mode(PROJECT_ROOT / "roles" / "svc-storage-nfs-client"),
            "host",
        )

    def test_role_with_stack_deploys_in_compose_mode(self):
        self.assertEqual(
            guide_select._guide_mode(PROJECT_ROOT / "roles" / "web-app-yourls"),
            "compose",
        )


class TestableRolesTests(unittest.TestCase):
    def test_pool_excludes_roles_whose_guide_mode_is_skipped(self):
        pool = guide_select._testable_roles()
        self.assertNotIn("svc-storage-nfs-client", pool)
        self.assertTrue(pool)

    def test_malformed_tests_yml_fails_selection_loudly(self):
        with TemporaryDirectory() as tmp:
            role_dir = Path(tmp) / "web-app-broken"
            tests_path = role_dir / ROLE_FILE_META_TESTS
            tests_path.parent.mkdir(parents=True)
            tests_path.write_text(
                textwrap.dedent(
                    """
                    ---
                    skip: not-a-list
                    """
                ),
                encoding="utf-8",
            )
            with self.assertRaises(MetaServicesShapeError):
                get_role_test_skips(role_dir, role_name=role_dir.name)


if __name__ == "__main__":
    unittest.main()
