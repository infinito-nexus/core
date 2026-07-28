"""The distro SPOT loader resolves names, families, images and platforms."""

from __future__ import annotations

import unittest

from utils.distros import (
    UnknownDistroError,
    dev_runtime_image,
    dev_runtime_images,
    distro_family,
    distro_names,
    environment_image,
    galaxy_platforms,
    pkgmgr_image,
)


class TestDistroSpot(unittest.TestCase):
    def test_names_are_the_build_matrix(self) -> None:
        self.assertEqual(
            distro_names(), ("arch", "debian", "ubuntu", "fedora", "centos")
        )

    def test_every_distro_maps_onto_an_os_family(self) -> None:
        self.assertEqual(
            distro_family(),
            {
                "arch": "Archlinux",
                "debian": "Debian",
                "ubuntu": "Debian",
                "fedora": "RedHat",
                "centos": "RedHat",
            },
        )

    def test_dev_runtime_images_follow_declaration_order(self) -> None:
        self.assertEqual(dev_runtime_images()[0], dev_runtime_image("arch"))
        self.assertEqual(len(dev_runtime_images()), len(distro_names()))

    def test_galaxy_platforms_are_sorted_by_name(self) -> None:
        names = [entry["name"] for entry in galaxy_platforms()]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names, ["ArchLinux", "Debian", "EL", "Fedora", "Ubuntu"])
        self.assertTrue(all(e["versions"] == ["all"] for e in galaxy_platforms()))

    def test_galaxy_platforms_are_not_shared_between_calls(self) -> None:
        first = galaxy_platforms()
        first[0]["versions"].append("mutated")
        self.assertEqual(galaxy_platforms()[0]["versions"], ["all"])

    def test_pkgmgr_image_renders_the_template(self) -> None:
        self.assertEqual(
            pkgmgr_image("arch", owner="acme", tag="stable"),
            "ghcr.io/acme/pkgmgr-arch:stable",
        )

    def test_environment_image_renders_the_template(self) -> None:
        self.assertEqual(
            environment_image("centos", owner="acme", repository="nexus", tag="ci-1"),
            "ghcr.io/acme/nexus/centos:ci-1",
        )

    def test_unknown_distro_is_rejected(self) -> None:
        with self.assertRaises(UnknownDistroError):
            pkgmgr_image("gentoo", owner="acme", tag="stable")


if __name__ == "__main__":
    unittest.main()
