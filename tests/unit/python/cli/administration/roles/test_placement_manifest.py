from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli.administration.roles import placement
from cli.administration.roles.declaration import PINNED_BY
from cli.administration.roles.marker import is_placed, provenance
from cli.administration.roles.placement import pull
from utils.roles.custom import MANIFEST_FILE, CustomRoleError
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from ._fixtures import (
    ROLE,
    ROLE_PATH,
    declaration,
    git,
    inventory,
    local_role,
    role_repo,
    roles_dir,
    write,
)

URL = "https://example.invalid/acme/demo.git"
OTHER = "web-app-cst-other"


class _ManifestFixture:
    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.roles = roles_dir(self.root / "core", "web-app-nextcloud")
        self.work = self.root / "core" / "build" / "custom-roles"
        self.repo = role_repo(self.root)
        write(self.repo / ROLE_PATH / ROLE_FILE_TASKS_MAIN, "release: v2\n")
        git(self.repo, "commit", "-q", "-am", "v2")
        git(self.repo, "tag", "-a", "v2.0.0", "-m", "v2")
        redirect = mock.patch.dict(
            os.environ,
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": f"url.{self.repo}.insteadOf",
                "GIT_CONFIG_VALUE_0": URL,
            },
        )
        redirect.start()
        self.addCleanup(redirect.stop)
        self.inventories = 0
        self.pin("v1.0.0")

    def commit_of(self, tag: str) -> str:
        return git(self.repo, "rev-parse", f"{tag}^{{commit}}").strip()

    def pin(self, version: str, commit: str | None = None) -> None:
        entry = {
            "url": URL,
            "version": version,
            "commit": commit or self.commit_of(version),
            "path": ROLE_PATH,
        }
        manifest = self.roles.parent / MANIFEST_FILE
        manifest.unlink(missing_ok=True)
        write(manifest, json.dumps({ROLE: entry}))

    def pull_inventory(self, applications: dict, groups: tuple[str, ...]) -> list[str]:
        self.inventories += 1
        base = self.root / f"inventory-{self.inventories}"
        return pull(inventory(base, list(groups), applications), self.roles, self.work)

    def release(self) -> str:
        tasks = self.roles / ROLE / ROLE_FILE_TASKS_MAIN
        return tasks.read_text(encoding="utf-8")  # nocheck: cache-read tempdir


class TestManifestPull(_ManifestFixture, unittest.TestCase):
    def test_pinned_role_is_placed_without_an_inventory(self):
        lines = pull(None, self.roles, self.work)
        self.assertEqual("release: v1\n", self.release())
        self.assertTrue(is_placed(self.roles / ROLE))
        self.assertTrue(provenance(self.roles / ROLE).endswith(PINNED_BY))
        self.assertRegex(lines[0], rf"^{ROLE}: {URL} .* @ v1\.0\.0 \(commit ")

    def test_host_list_pulls_the_pinned_role(self):
        pull(Path("localhost,"), self.roles, self.work)
        self.assertTrue(is_placed(self.roles / ROLE))

    def test_annotated_tag_is_checked_against_its_peeled_commit(self):
        self.pin("v2.0.0")
        pull(None, self.roles, self.work)
        self.assertEqual("release: v2\n", self.release())

    def test_tag_that_resolves_to_another_commit_stops_naming_both(self):
        pinned = "f" * 40
        self.pin("v1.0.0", pinned)
        with self.assertRaises(CustomRoleError) as refused:
            pull(None, self.roles, self.work)
        message = str(refused.exception)
        self.assertIn(ROLE, message)
        self.assertIn(self.commit_of("v1.0.0"), message)
        self.assertIn(pinned, message)
        self.assertEqual(
            ["web-app-nextcloud"], sorted(p.name for p in self.roles.iterdir())
        )

    def test_branch_as_version_is_refused(self):
        self.pin("feature", self.commit_of("feature"))
        with self.assertRaisesRegex(CustomRoleError, "'feature' is no release tag"):
            pull(None, self.roles, self.work)

    def test_branch_named_like_a_release_is_refused(self):
        git(self.repo, "branch", "v3.0.0", "feature")
        self.pin("v3.0.0", self.commit_of("feature"))
        with self.assertRaisesRegex(CustomRoleError, "'v3.0.0' names a branch"):
            pull(None, self.roles, self.work)
        self.assertFalse((self.roles / ROLE).exists())

    def test_current_pin_is_kept_without_fetching(self):
        pull(None, self.roles, self.work)
        with mock.patch.object(placement, "stage") as stage:
            lines = pull(None, self.roles, self.work)
        stage.assert_not_called()
        self.assertIn(f"{ROLE}: kept as placed", lines[0])

    def test_changed_pin_replaces_the_placed_role(self):
        pull(None, self.roles, self.work)
        self.pin("v2.0.0")
        pull(None, self.roles, self.work)
        self.assertEqual("release: v2\n", self.release())

    def test_pull_without_an_inventory_removes_nothing(self):
        checkout = local_role(self.root, OTHER)
        self.pull_inventory(
            {OTHER: declaration(str(checkout), None, f"ansible/roles/{OTHER}")},
            (OTHER,),
        )
        pull(None, self.roles, self.work)
        self.assertTrue(is_placed(self.roles / OTHER))
        self.assertTrue(is_placed(self.roles / ROLE))


class TestManifestPrecedence(_ManifestFixture, unittest.TestCase):
    def test_inventory_pin_overrides_the_manifest(self):
        self.pull_inventory({ROLE: declaration(URL, "v2.0.0")}, (ROLE,))
        self.assertEqual("release: v2\n", self.release())
        self.assertFalse(provenance(self.roles / ROLE).endswith(PINNED_BY))

    def test_pull_without_an_inventory_keeps_the_override(self):
        self.pull_inventory({ROLE: declaration(URL, "v2.0.0")}, (ROLE,))
        with mock.patch.object(placement, "stage") as stage:
            pull(None, self.roles, self.work)
        stage.assert_not_called()
        self.assertEqual("release: v2\n", self.release())

    def test_source_without_custom_overrides_a_pinned_role(self):
        source = declaration(URL, "v2.0.0")["source"]
        self.pull_inventory({ROLE: {"source": source}}, (ROLE,))
        self.assertEqual("release: v2\n", self.release())

    def test_pinned_group_needs_neither_custom_nor_source_in_the_inventory(self):
        self.pull_inventory({}, (ROLE,))
        self.assertEqual("release: v1\n", self.release())

    def test_inventory_pull_places_the_pinned_role_it_does_not_declare(self):
        self.pull_inventory({}, ())
        self.assertTrue(is_placed(self.roles / ROLE))

    def test_inventory_pull_restores_the_manifest_pin_after_an_override(self):
        self.pull_inventory({ROLE: declaration(URL, "v2.0.0")}, (ROLE,))
        self.pull_inventory({}, ())
        self.assertEqual("release: v1\n", self.release())
        self.assertTrue(provenance(self.roles / ROLE).endswith(PINNED_BY))


if __name__ == "__main__":
    unittest.main()
