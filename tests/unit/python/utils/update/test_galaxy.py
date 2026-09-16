import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.update.galaxy import apply_updates, collect_pins, find_outdated_updates

GALAXY = """---
collections:
  - name: community.general
    version: 13.2.0
  - name: kewlfft.aur
    version: 0.13.0
"""

GIT = """---
collections:
  - name: community.general
    source: https://github.com/ansible-collections/community.general.git
    type: git
    version: 13.2.0

  - name: kewlfft.aur
    source: https://github.com/kewlfft/ansible-aur.git
    type: git
    version: master
"""


def _read(root: Path, name: str) -> str:
    path = root / "requirements" / name
    return path.read_text()  # nocheck: cache-read -- rewritten by this test


def _repo(root: Path) -> Path:
    (root / "requirements").mkdir()
    (root / "requirements" / "requirements.galaxy.yml").write_text(
        GALAXY, encoding="utf-8"
    )
    (root / "requirements" / "requirements.git.yml").write_text(GIT, encoding="utf-8")
    return root


class TestCollectPins(unittest.TestCase):
    def test_only_collections_pinned_to_a_semver_in_both_files_are_collected(self):
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))

            pins = collect_pins(root)

            self.assertEqual([pin.fqcn for pin in pins], ["community.general"])

    def test_a_version_the_two_files_disagree_on_is_not_collected(self):
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            (root / "requirements" / "requirements.galaxy.yml").write_text(
                GALAXY.replace("13.2.0", "13.4.0"), encoding="utf-8"
            )

            self.assertEqual(collect_pins(root), [])


class TestFindOutdatedUpdates(unittest.TestCase):
    def test_a_higher_tag_of_the_same_depth_is_an_update(self):
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            with patch(
                "utils.update.galaxy.git_ls_remote_tags",
                return_value=["13.1.0", "13.2.0", "13.4.0"],
            ):
                updates = find_outdated_updates(root)

            self.assertEqual([u.latest for u in updates], ["13.4.0"])

    def test_the_newest_tag_already_pinned_is_no_update(self):
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            with patch(
                "utils.update.galaxy.git_ls_remote_tags",
                return_value=["13.1.0", "13.2.0"],
            ):
                self.assertEqual(find_outdated_updates(root), [])

    def test_a_tag_of_a_different_depth_is_not_a_candidate(self):
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            with patch(
                "utils.update.galaxy.git_ls_remote_tags",
                return_value=["13.2.0", "14"],
            ):
                self.assertEqual(find_outdated_updates(root), [])


class TestApplyUpdates(unittest.TestCase):
    def test_both_requirement_files_are_bumped_together(self):
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            with patch(
                "utils.update.galaxy.git_ls_remote_tags",
                return_value=["13.4.0"],
            ):
                updates = find_outdated_updates(root)
                changed = apply_updates(root, updates)

            self.assertEqual(len(changed), 2)
            galaxy_text = _read(root, "requirements.galaxy.yml")
            git_text = _read(root, "requirements.git.yml")
            self.assertIn("version: 13.4.0", galaxy_text)
            self.assertIn("version: 13.4.0", git_text)
            self.assertNotIn("13.2.0", galaxy_text)
            self.assertNotIn("13.2.0", git_text)

    def test_an_entry_outside_the_update_keeps_its_version(self):
        with TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            with patch(
                "utils.update.galaxy.git_ls_remote_tags",
                return_value=["13.4.0"],
            ):
                apply_updates(root, find_outdated_updates(root))

            self.assertIn("version: master", _read(root, "requirements.git.yml"))
            self.assertIn("version: 0.13.0", _read(root, "requirements.galaxy.yml"))


if __name__ == "__main__":
    unittest.main()
