"""Unit test: the relevant-delta check counts every path for a rerun that runs
the tests, leaves out what no deploy reads for a deploy-only rerun, counts a
path outside roles/ and the files of every role under test, treats no role
under test as relevant, and lets another role count only when the
affected-roles resolver lists one under test."""

from __future__ import annotations

import unittest

from agents.routines.tools.delta import deployed_paths, relevant, role_file, role_ids
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_README,
    ROLE_FILE_TASKS_MAIN,
)

_ROLE = "web-app-gitea"
_ROLES = {_ROLE}
_OWN = f"roles/{_ROLE}/{ROLE_FILE_TASKS_MAIN}"
_OTHER = f"roles/svc-db-postgres/{ROLE_FILE_TASKS_MAIN}"
_SHARED = "group_vars/all/00_general.yml"
_NOT_DEPLOYED = (
    "docs/contributing/actions/deploy.md",
    ROLE_FILE_README,
    "tests/unit/x.py",
)


class TestRoleFile(unittest.TestCase):
    def test_splits_a_role_path(self) -> None:
        self.assertEqual(
            role_file(f"roles/{_ROLE}/{ROLE_FILE_META_SERVICES}"),
            (_ROLE, ROLE_FILE_META_SERVICES),
        )

    def test_none_outside_roles(self) -> None:
        self.assertIsNone(role_file(_SHARED))
        self.assertIsNone(role_file(f"roles/{_ROLE}"))


class TestRoleIds(unittest.TestCase):
    def test_drops_the_variant_narrowing_and_empty_tokens(self) -> None:
        self.assertEqual(
            role_ids([f"{_ROLE}#0,2", "", "svc-runner"]), {_ROLE, "svc-runner"}
        )


class TestDeployedPaths(unittest.TestCase):
    def test_tests_and_docs_outside_roles_are_left_out(self) -> None:
        self.assertEqual(deployed_paths([*_NOT_DEPLOYED, _SHARED]), [_SHARED])

    def test_a_role_readme_stays(self) -> None:
        readme = f"roles/{_ROLE}/{ROLE_FILE_README}"
        self.assertEqual(deployed_paths([readme]), [readme])


class TestRelevant(unittest.TestCase):
    def test_nothing_deployed_is_not_relevant_to_a_deploy(self) -> None:
        self.assertFalse(relevant(_ROLES, list(_NOT_DEPLOYED), "__ALL__", False))
        self.assertFalse(relevant(_ROLES, [], "__ALL__", False))

    def test_a_run_of_the_tests_reads_every_path(self) -> None:
        self.assertTrue(relevant(_ROLES, ["tests/unit/x.py"], "", True))
        self.assertFalse(relevant(_ROLES, [], "", True))

    def test_own_role_file_is_relevant(self) -> None:
        self.assertTrue(relevant(_ROLES, [_OWN], "svc-db-postgres", False))

    def test_shared_path_is_relevant(self) -> None:
        self.assertTrue(relevant(_ROLES, [_SHARED], "svc-db-postgres", False))

    def test_no_role_under_test_is_relevant(self) -> None:
        self.assertTrue(relevant(set(), [_OWN], _ROLE, False))

    def test_a_second_role_under_test_is_relevant(self) -> None:
        self.assertTrue(relevant({_ROLE, "svc-db-postgres"}, [_OTHER], "x", False))

    def test_other_role_not_listed_is_not_relevant(self) -> None:
        self.assertFalse(
            relevant(_ROLES, [_OTHER], "svc-db-postgres web-app-mig", False)
        )

    def test_other_role_listed_with_variants_is_relevant(self) -> None:
        self.assertTrue(
            relevant(_ROLES, [_OTHER], f"svc-db-postgres {_ROLE}#0,2", False)
        )

    def test_full_or_missing_resolver_output_is_relevant(self) -> None:
        self.assertTrue(relevant(_ROLES, [_OTHER], "__ALL__", False))
        self.assertTrue(relevant(_ROLES, [_OTHER], "", False))


if __name__ == "__main__":
    unittest.main()
