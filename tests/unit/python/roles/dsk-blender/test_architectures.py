from __future__ import annotations

import unittest

from utils.github.variant.pins import draw_pair, row_architectures, row_pairs
from utils.github.variant.pools import ARCHITECTURES, DISTROS

ROLE = "dsk-blender"
UNPUBLISHED = {"centos", "arch"}


def _drawn() -> set[tuple[str, str]]:
    architectures = row_architectures(ROLE, ARCHITECTURES)
    pairs = row_pairs(ROLE, DISTROS, architectures)
    return {
        draw_pair(
            pairs,
            DISTROS,
            architectures,
            pin_distro=None,
            pin_architecture=None,
            index=index,
            sweep=sweep,
        )
        for index in range(len(DISTROS) * len(ARCHITECTURES))
        for sweep in range(len(ARCHITECTURES))
    }


class TestBlenderArchitectures(unittest.TestCase):
    def test_the_role_keeps_every_architecture(self) -> None:
        self.assertEqual(row_architectures(ROLE, ARCHITECTURES), ARCHITECTURES)

    def test_the_matrix_never_plans_arch_on_arm64(self) -> None:
        self.assertNotIn(
            ("arch", "arm64"),
            _drawn(),
            "Arch Linux ARM carries no blender package "
            "(http://mirror.archlinuxarm.org/aarch64/extra/), so pacman aborts "
            "with 'could not find or read package'",
        )

    def test_the_matrix_never_plans_centos_on_arm64(self) -> None:
        self.assertNotIn(
            ("centos", "arm64"),
            _drawn(),
            "centos installs org.blender.Blender from Flathub, which publishes "
            "it for x86_64 only "
            "(https://flathub.org/api/v2/summary/org.blender.Blender), "
            "so the flatpak task aborts there with "
            "'Nothing matches org.blender.Blender in remote flathub'",
        )

    def test_every_other_distro_still_runs_on_arm64(self) -> None:
        self.assertEqual(
            {distro for distro, architecture in _drawn() if architecture == "arm64"},
            set(DISTROS) - UNPUBLISHED,
        )


if __name__ == "__main__":
    unittest.main()
