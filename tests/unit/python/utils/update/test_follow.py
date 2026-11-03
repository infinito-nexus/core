from __future__ import annotations

import unittest
from unittest import mock

from utils.update.follow import followed_tags

UBUNTU = {
    "latest": "sha256:lts",
    "26.04": "sha256:lts",
    "26.10": "sha256:interim",
    "rolling": "sha256:interim",
}
FEDORA = {
    "latest": "sha256:45",
    "44": "sha256:44",
    "45": "sha256:45",
    "46": "sha256:rawhide",
    "rawhide": "sha256:rawhide",
}


def _digests(table: dict[str, str]):
    return lambda _image, tag: table[tag]


class TestFollowedTags(unittest.TestCase):
    def test_ubuntu_on_the_lts_gets_no_interim_release(self) -> None:
        with mock.patch("utils.update.follow.tag_digest", _digests(UBUNTU)):
            found = followed_tags("ubuntu", list(UBUNTU), {"follow": "latest"}, "26.04")
        self.assertEqual(found, [])

    def test_fedora_moves_to_the_stable_release_not_rawhide(self) -> None:
        with mock.patch("utils.update.follow.tag_digest", _digests(FEDORA)):
            found = followed_tags("fedora", list(FEDORA), {"follow": "latest"}, "44")
        self.assertEqual(found, ["45"])

    def test_an_entity_without_follow_keeps_every_tag(self) -> None:
        tags = list(FEDORA)
        self.assertEqual(followed_tags("fedora", tags, {"version": "44"}, "44"), tags)
        self.assertEqual(followed_tags("fedora", tags, None, "44"), tags)

    def test_an_unreadable_registry_proposes_nothing(self) -> None:
        with mock.patch("utils.update.follow.tag_digest", side_effect=OSError):
            found = followed_tags("fedora", list(FEDORA), {"follow": "latest"}, "44")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
