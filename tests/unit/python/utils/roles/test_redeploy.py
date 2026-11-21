from __future__ import annotations

import unittest

from utils.roles import redeploy
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC, ROLE_FILE_TASKS_MAIN

ROLE = "web-app-a"


def _path(role: str, rel: str) -> str:
    return f"roles/{role}/{rel}"


class TestComposeRedeploy(unittest.TestCase):
    def test_every_inventory_file_of_any_role_takes_a_reinstall(self) -> None:
        for rel in sorted(redeploy.INVENTORY_FILES):
            for role in (ROLE, "web-app-b"):
                with self.subTest(rel=rel, role=role):
                    self.assertEqual(
                        redeploy.compose_redeploy(ROLE, [_path(role, rel)]),
                        redeploy.REINSTALL,
                    )

    def test_every_shared_meta_and_test_file_takes_an_update(self) -> None:
        for rel in [*sorted(redeploy.OUTSIDE_SYNC_FILES), "files/test/x.py"]:
            with self.subTest(rel=rel):
                self.assertEqual(
                    redeploy.compose_redeploy(ROLE, [_path(ROLE, rel)]),
                    redeploy.UPDATE,
                )

    def test_own_role_file_takes_a_role_sync(self) -> None:
        self.assertEqual(
            redeploy.compose_redeploy(ROLE, [_path(ROLE, ROLE_FILE_TASKS_MAIN)]),
            redeploy.ROLE_SYNC,
        )

    def test_test_and_document_paths_reach_no_deploy(self) -> None:
        for extra in ("tests/unit/python/x.py", "docs/x.md", "README.md"):
            with self.subTest(extra=extra):
                paths = [_path(ROLE, ROLE_FILE_TASKS_MAIN), extra]
                self.assertEqual(
                    redeploy.compose_redeploy(ROLE, paths), redeploy.ROLE_SYNC
                )

    def test_negative_control_a_role_document_still_counts(self) -> None:
        paths = [_path(ROLE, ROLE_FILE_TASKS_MAIN), _path("web-app-b", "README.md")]
        self.assertEqual(redeploy.compose_redeploy(ROLE, paths), redeploy.UPDATE)

    def test_negative_control_another_roles_file_takes_an_update(self) -> None:
        paths = [
            _path(ROLE, ROLE_FILE_TASKS_MAIN),
            _path("web-app-b", ROLE_FILE_TASKS_MAIN),
        ]
        self.assertEqual(redeploy.compose_redeploy(ROLE, paths), redeploy.UPDATE)

    def test_non_role_path_empty_diff_and_empty_role_take_an_update(self) -> None:
        for role, paths in (
            (ROLE, ["plugins/filter/x.py"]),
            (ROLE, []),
            ("", [_path(ROLE, ROLE_FILE_TASKS_MAIN)]),
        ):
            with self.subTest(role=role, paths=paths):
                self.assertEqual(
                    redeploy.compose_redeploy(role, paths), redeploy.UPDATE
                )


class TestSpecOnly(unittest.TestCase):
    def test_spec_folder_is_spec_only(self) -> None:
        self.assertTrue(
            redeploy.spec_only(
                [
                    _path(ROLE, ROLE_FILE_PLAYWRIGHT_SPEC),
                    _path(ROLE, "files/playwright/a.js"),
                ]
            )
        )

    def test_negative_control_any_other_file_is_not(self) -> None:
        self.assertFalse(
            redeploy.spec_only(
                [
                    _path(ROLE, ROLE_FILE_PLAYWRIGHT_SPEC),
                    _path(ROLE, ROLE_FILE_TASKS_MAIN),
                ]
            )
        )

    def test_empty_diff_is_not_spec_only(self) -> None:
        self.assertFalse(redeploy.spec_only([]))


if __name__ == "__main__":
    unittest.main()
