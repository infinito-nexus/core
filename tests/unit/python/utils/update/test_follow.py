from __future__ import annotations

import contextlib
import io
import json
import unittest
import urllib.error
from unittest import mock

from utils.update.follow import followed_tags, tag_digest

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

    def test_an_unreadable_registry_proposes_nothing_and_says_so(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch("utils.update.follow.tag_digest", side_effect=OSError("429")),
            contextlib.redirect_stderr(stderr),
        ):
            found = followed_tags("fedora", list(FEDORA), {"follow": "latest"}, "44")
        self.assertEqual(found, [])
        self.assertIn("WARN fedora:44", stderr.getvalue())

    def test_a_rate_limited_digest_is_retried(self) -> None:
        limited = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        body = json.dumps({"digest": "sha256:45"}).encode()
        with (
            mock.patch("utils.update.follow.get", side_effect=[limited, body]),
            mock.patch("utils.update.follow.time.sleep"),
        ):
            self.assertEqual(tag_digest("fedora", "latest"), "sha256:45")

    def test_a_persistent_rate_limit_still_raises(self) -> None:
        limited = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        with (
            mock.patch("utils.update.follow.get", side_effect=[limited] * 3),
            mock.patch("utils.update.follow.time.sleep"),
            self.assertRaises(urllib.error.HTTPError),
        ):
            tag_digest("fedora", "latest")


if __name__ == "__main__":
    unittest.main()
