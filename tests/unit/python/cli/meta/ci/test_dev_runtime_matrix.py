"""Contract of the workspace track split."""

from __future__ import annotations

import unittest

from cli.meta.ci.dev_runtime import image_label, workspace_matrix
from utils.symbol_glossary import to_emoji

IMAGES = ["debian:bookworm", "fedora:latest", "ubuntu:latest", "quay.io/centos:latest"]


class TestWorkspaceMatrix(unittest.TestCase):
    def test_one_entry_per_image_and_never_more(self) -> None:
        for mode in ("rotate", "compose", "swarm"):
            with self.subTest(mode=mode):
                entries = workspace_matrix(IMAGES, mode, 1)
                self.assertEqual([e["image"] for e in entries], IMAGES)

    def test_a_pinned_mode_puts_every_image_on_that_track(self) -> None:
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                tracks = {e["track"] for e in workspace_matrix(IMAGES, mode, 7)}
                self.assertEqual(tracks, {mode})

    def test_rotate_splits_the_images_across_both_tracks(self) -> None:
        tracks = [e["track"] for e in workspace_matrix(IMAGES, "rotate", 0)]
        self.assertEqual(tracks, ["compose", "swarm", "compose", "swarm"])

    def test_consecutive_runs_flip_every_image(self) -> None:
        even = workspace_matrix(IMAGES, "rotate", 4)
        odd = workspace_matrix(IMAGES, "rotate", 5)
        for a, b in zip(even, odd, strict=True):
            self.assertEqual(a["image"], b["image"])
            self.assertNotEqual(a["track"], b["track"])

    def test_two_consecutive_runs_cover_both_tracks_per_image(self) -> None:
        seen: dict[str, set[str]] = {image: set() for image in IMAGES}
        for run in (11, 12):
            for entry in workspace_matrix(IMAGES, "rotate", run):
                seen[entry["image"]].add(entry["track"])
        for image, tracks in seen.items():
            with self.subTest(image=image):
                self.assertEqual(tracks, {"compose", "swarm"})

    def test_an_odd_image_count_still_uses_both_tracks(self) -> None:
        tracks = [e["track"] for e in workspace_matrix(IMAGES[:3], "rotate", 0)]
        self.assertEqual(tracks, ["compose", "swarm", "compose"])

    def test_the_icon_comes_from_the_symbol_glossary(self) -> None:
        for entry in workspace_matrix(IMAGES, "rotate", 3):
            with self.subTest(image=entry["image"]):
                self.assertEqual(entry["icon"], to_emoji(entry["track"]))

    def test_a_label_keeps_only_the_last_two_segments(self) -> None:
        self.assertEqual(image_label("quay.io/centos/centos:latest"), "centos:latest")
        self.assertEqual(image_label("manjarolinux/base"), "manjarolinux/base")
        self.assertEqual(image_label("debian:bookworm"), "debian:bookworm")
        self.assertEqual(image_label("ghcr.io/foo/bar/baz:1.2"), "baz:1.2")
        self.assertEqual(image_label("plainname"), "plainname")


if __name__ == "__main__":
    unittest.main()
