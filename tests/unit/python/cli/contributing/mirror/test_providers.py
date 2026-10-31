from __future__ import annotations

import unittest
from unittest.mock import patch

from cli.contributing.mirror.model import ImageRef
from cli.contributing.mirror.providers import GHCRProvider


class TestGHCRProviderImageBase(unittest.TestCase):
    def setUp(self) -> None:
        self.image = ImageRef(
            role="web-app-nextcloud",
            service="app",
            name="nextcloud",
            version="31.0.0",
            source="docker.io/library/nextcloud:31.0.0",
            registry="docker.io",
        )

    def test_image_base_simple(self) -> None:
        provider = GHCRProvider("acme", "myrepo")
        self.assertEqual(
            provider.image_base(self.image),
            "ghcr.io/acme/myrepo/mirror/docker.io/nextcloud",
        )

    def test_image_base_with_slash_in_name(self) -> None:
        image = ImageRef(
            role="web-app-foo",
            service="svc",
            name="foo/bar",
            version="1.0",
            source="docker.io/foo/bar:1.0",
            registry="docker.io",
        )
        provider = GHCRProvider("acme", "myrepo")
        self.assertEqual(
            provider.image_base(image),
            "ghcr.io/acme/myrepo/mirror/docker.io/foo/bar",
        )

    def test_image_base_quay(self) -> None:
        image = ImageRef(
            role="web-app-keycloak",
            service="app",
            name="keycloak/keycloak",
            version="latest",
            source="quay.io/keycloak/keycloak:latest",
            registry="quay.io",
        )
        provider = GHCRProvider("acme", "myrepo")
        self.assertEqual(
            provider.image_base(image),
            "ghcr.io/acme/myrepo/mirror/quay.io/keycloak/keycloak",
        )

    def test_namespace_and_repository_are_lowercased(self) -> None:
        provider = GHCRProvider("ACME", "MyRepo")
        self.assertEqual(provider.namespace, "acme")
        self.assertEqual(provider.repository, "myrepo")


class TestGHCRProviderIsStale(unittest.TestCase):
    UPSTREAM = "docker.io/roundcube/roundcubemail"
    MIRROR = "ghcr.io/acme/myrepo/mirror/docker.io/roundcube/roundcubemail"

    def setUp(self) -> None:
        self.image = ImageRef(
            role="web-app-stalwart",
            service="webmail",
            name="roundcube/roundcubemail",
            version="1.7.5-apache",
            source="docker.io/roundcube/roundcubemail:1.7.5-apache",
            registry="docker.io",
        )
        self.provider = GHCRProvider("acme", "myrepo")

    def _is_stale(self, digests: dict) -> bool:
        def fake(image: str, reference: str) -> str | None:
            self.assertEqual(reference, "1.7.5-apache")
            return digests[image]

        with patch(
            "cli.contributing.mirror.providers.manifest_digest", side_effect=fake
        ):
            return self.provider.is_stale(self.image)

    def test_upstream_repushed_tag_makes_the_copy_stale(self) -> None:
        self.assertTrue(
            self._is_stale({self.UPSTREAM: "sha256:new", self.MIRROR: "sha256:old"})
        )

    def test_matching_digests_are_current(self) -> None:
        self.assertFalse(
            self._is_stale({self.UPSTREAM: "sha256:same", self.MIRROR: "sha256:same"})
        )

    def test_indeterminate_upstream_counts_as_current(self) -> None:
        self.assertFalse(
            self._is_stale({self.UPSTREAM: None, self.MIRROR: "sha256:old"})
        )

    def test_indeterminate_mirror_counts_as_current(self) -> None:
        self.assertFalse(
            self._is_stale({self.UPSTREAM: "sha256:new", self.MIRROR: None})
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
