from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from cli.contributing.update.custom_roles.__main__ import main
from tests.unit.python.cli.administration.roles._fixtures import git, write
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.roles.custom import MANIFEST_FILE
from utils.update.custom_roles import apply_updates, find_outdated_updates

ROLE = "web-app-cst-cosmos"
OTHER = "web-app-cst-other"


class TestCustomRolesUpdater(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "cosmos"
        self.commits: dict[str, str] = {}
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.release("v0.1.0", annotated=False)
        self.release("v0.2.0", annotated=True)
        self.release("v0.3.0-rc.1", annotated=True)
        self.release("latest", annotated=False)
        self.core = self.root / "core"

    def release(self, tag: str, annotated: bool) -> None:
        write(self.repo / "README.md", f"{tag}\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", tag)
        if annotated:
            git(self.repo, "tag", "-a", tag, "-m", tag)
        else:
            git(self.repo, "tag", tag)
        self.commits[tag] = git(self.repo, "rev-parse", "HEAD").strip()

    def manifest(self, entries: dict[str, tuple[str, str]]) -> Path:
        text = "---\n" + "".join(
            f"{group}:\n  url: {self.repo}\n  version: {version}\n"
            f"  commit: {commit}\n  path: ansible/roles/{group}\n"
            for group, (version, commit) in entries.items()
        )
        return write(self.core / MANIFEST_FILE, text)

    def test_newest_release_tag_wins_over_latest_and_prereleases(self):
        self.manifest({ROLE: ("v0.1.0", self.commits["v0.1.0"])})
        updates = find_outdated_updates(self.core)
        self.assertEqual(1, len(updates))
        self.assertEqual("v0.2.0", updates[0].version)
        self.assertEqual(self.commits["v0.2.0"], updates[0].commit)

    def test_annotated_tag_writes_its_peeled_commit(self):
        tag_object = git(self.repo, "rev-parse", "v0.2.0").strip()
        self.assertNotEqual(tag_object, self.commits["v0.2.0"])
        self.manifest({ROLE: ("v0.1.0", self.commits["v0.1.0"])})
        updates = find_outdated_updates(self.core)
        self.assertEqual(self.commits["v0.2.0"], updates[0].commit)

    def test_apply_rewrites_version_and_commit_of_that_role_only(self):
        manifest = self.manifest(
            {
                ROLE: ("v0.1.0", self.commits["v0.1.0"]),
                OTHER: ("v0.2.0", self.commits["v0.2.0"]),
            }
        )
        updates = find_outdated_updates(self.core)
        self.assertEqual([ROLE], [update.pin.group for update in updates])
        self.assertEqual([manifest], apply_updates(self.core, updates))
        text = manifest.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        cosmos, other = text.split(f"{OTHER}:\n")
        self.assertIn("version: v0.2.0\n", cosmos)
        self.assertIn(f"commit: {self.commits['v0.2.0']}\n", cosmos)
        self.assertNotIn(self.commits["v0.1.0"], cosmos)
        self.assertIn(f"commit: {self.commits['v0.2.0']}\n", other)

    def test_current_pin_is_left_alone(self):
        self.manifest({ROLE: ("v0.2.0", self.commits["v0.2.0"])})
        self.assertEqual([], find_outdated_updates(self.core))
        self.assertEqual([], apply_updates(self.core, []))

    def test_update_whose_entry_is_gone_changes_nothing(self):
        self.manifest({ROLE: ("v0.1.0", self.commits["v0.1.0"])})
        updates = find_outdated_updates(self.core)
        manifest = self.manifest({OTHER: ("v0.1.0", self.commits["v0.1.0"])})
        before = manifest.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertEqual([], apply_updates(self.core, updates))
        after = manifest.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertEqual(before, after)

    def test_moving_tag_as_pin_is_never_bumped(self):
        self.manifest({ROLE: ("latest", self.commits["latest"])})
        self.assertEqual([], find_outdated_updates(self.core))

    def test_failed_lookup_leaves_the_pin(self):
        write(
            self.core / MANIFEST_FILE,
            f"{ROLE}:\n  url: {self.root / 'absent'}\n  version: v0.1.0\n"
            f"  commit: {self.commits['v0.1.0']}\n  path: ansible/roles/{ROLE}\n",
        )
        self.assertEqual([], find_outdated_updates(self.core))

    def test_missing_manifest_pins_nothing(self):
        self.assertEqual([], find_outdated_updates(self.core))

    def test_the_module_writes_the_newest_release_and_its_peeled_commit(self):
        manifest = self.manifest({ROLE: ("v0.1.0", self.commits["v0.1.0"])})
        argv = ["custom_roles", "--repo-root", str(self.core)]
        with (
            mock.patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(0, main())
        text = manifest.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertIn("version: v0.2.0\n", text)
        self.assertIn(f"commit: {self.commits['v0.2.0']}\n", text)


class TestCustomRolesDocumentation(unittest.TestCase):
    def test_deploy_md_and_the_update_readme_document_the_manifest(self):
        documents = {
            PROJECT_ROOT / "docs" / "administration" / "deploy.md": (
                "meta/custom_roles.yml",
                "`https` URL of a public repository without credentials",
                "release tag `vX.Y.Z` or `X.Y.Z`",
                "with or without `custom: true`",
                "`make roles-pull` without `inventory`",
                "python -m cli.contributing.update.custom_roles",
            ),
            PROJECT_ROOT / "cli" / "contributing" / "update" / "README.md": (
                "python -m cli.contributing.update.custom_roles",
                "peels to",
                "update-custom-roles",
            ),
        }
        for path, phrases in documents.items():
            text = read_text(str(path))
            for phrase in phrases:
                with self.subTest(document=path.name, phrase=phrase):
                    self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
