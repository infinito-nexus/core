from __future__ import annotations

import unittest

from utils.docker.image.discovery import docker_hub_source, image_source
from utils.docker.image.pin import (
    DIGEST,
    REF,
    RULE_BY_CLASS,
    SEMVER,
    is_digest,
    pin_class,
    pull_reference,
    reference_separator,
)

DIGEST_VALUE = "sha256:d5591131b1d898cd02fc7a17adb8ea026352d67809bc9289707778e9e03a76a4"


class TestPinClass(unittest.TestCase):
    def test_a_semver_tag_is_a_semver_pin(self):
        for value in ("3.0.1", "16", "17-3.5", "5.4.5-php8.3-apache", "v1.12.27"):
            self.assertEqual(pin_class(value), SEMVER, value)

    def test_a_content_address_is_a_digest_pin(self):
        self.assertEqual(pin_class(DIGEST_VALUE), DIGEST)

    def test_a_moving_name_is_neither(self):
        for value in ("latest", "main", "stable", "buildx-stable-1"):
            self.assertEqual(pin_class(value), REF, value)

    def test_surrounding_whitespace_does_not_change_the_class(self):
        self.assertEqual(pin_class(f"  {DIGEST_VALUE}  "), DIGEST)
        self.assertEqual(pin_class("  3.0.1  "), SEMVER)

    def test_a_digest_declares_itself_apart_from_a_tag(self):
        self.assertNotEqual(
            RULE_BY_CLASS[DIGEST],
            RULE_BY_CLASS[REF],
            "a digest is chosen for a reason a non-semver tag never carries, so "
            "the two cannot share one marker",
        )
        self.assertEqual(RULE_BY_CLASS[DIGEST], "docker-digest")
        self.assertEqual(RULE_BY_CLASS[REF], "docker-version")

    def test_a_semver_pin_needs_no_declaration(self):
        self.assertNotIn(SEMVER, RULE_BY_CLASS)


class TestPullReference(unittest.TestCase):
    def test_a_digest_is_joined_with_an_at_sign(self):
        self.assertEqual(reference_separator(DIGEST_VALUE), "@")
        self.assertEqual(
            pull_reference("ghcr.io/owner/app", DIGEST_VALUE),
            f"ghcr.io/owner/app@{DIGEST_VALUE}",
        )

    def test_a_tag_is_joined_with_a_colon(self):
        self.assertEqual(reference_separator("3.0.1"), ":")
        self.assertEqual(
            pull_reference("ghcr.io/owner/app", "3.0.1"), "ghcr.io/owner/app:3.0.1"
        )

    def test_is_digest_rejects_a_tag_that_merely_mentions_sha256(self):
        self.assertFalse(is_digest("v2-sha256:abc"))


class TestSourceKeepsTheDigest(unittest.TestCase):
    """A pull ref that silently drops the digest pins nothing at all."""

    def test_image_source_keeps_a_digest(self):
        self.assertEqual(
            image_source("ghcr.io/owner/app", DIGEST_VALUE),
            f"ghcr.io/owner/app@{DIGEST_VALUE}",
        )

    def test_image_source_still_tags_a_semver(self):
        self.assertEqual(
            image_source("ghcr.io/owner/app", "3.0.1"), "ghcr.io/owner/app:3.0.1"
        )

    def test_docker_hub_source_keeps_a_digest(self):
        self.assertEqual(
            docker_hub_source("postgres", DIGEST_VALUE),
            f"docker.io/library/postgres@{DIGEST_VALUE}",
        )

    def test_a_digest_never_yields_a_tag_separator(self):
        source = image_source("quay.io/owner/app", DIGEST_VALUE)

        self.assertNotIn(
            f":{DIGEST_VALUE}",
            source,
            "a colon here would make the registry read the digest as a tag name",
        )


if __name__ == "__main__":
    unittest.main()
