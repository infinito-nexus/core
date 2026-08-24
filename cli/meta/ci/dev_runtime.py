"""Answer the development-runtime matrix questions from the distro SPOT.

Exists so workflow steps can ask for the matrix, and for the distro behind a
matrix entry, without embedding a python one-liner per question.

    python3 -m cli.meta.ci.dev_runtime images
    python3 -m cli.meta.ci.dev_runtime distro --image fedora:latest
    python3 -m cli.meta.ci.dev_runtime matrix --mode rotate --run 42
"""

from __future__ import annotations

import argparse
import json
import sys

from utils.distros import (
    FILE_META_DISTROS,
    dev_runtime_images,
    distro_of_dev_runtime_image,
)
from utils.symbol_glossary import to_emoji

TRACKS = ("compose", "swarm")


def image_label(image: str) -> str:
    """Shorten a dev-runtime image to its last two registry segments.

    ``quay.io/centos/centos:latest`` becomes ``centos:latest``; a two-segment
    image such as ``debian:bookworm`` is returned unchanged.

    Args:
        image: full image reference.

    Returns:
        The last two segments, joined by the separator that preceded the last.
    """
    head, sep, tail = image.rpartition(":")
    if not sep:
        head, sep, tail = image.rpartition("/")
    if not sep:
        return image
    return f"{head.rpartition('/')[2]}{sep}{tail}"


def workspace_matrix(images: list[str], mode: str, run: int) -> list[dict[str, str]]:
    """Assign exactly one workspace track to every dev-runtime image.

    Args:
        images: dev-runtime images, in SPOT order.
        mode: ``compose`` or ``swarm`` to pin every image to that track,
            ``rotate`` to split the images across both.
        run: run number; its parity flips a rotated split, so two consecutive
            runs cover both tracks on every image.

    Returns:
        One ``{"image", "track", "icon", "label"}`` entry per image.
    """
    tracks = (
        [mode] * len(images)
        if mode in TRACKS
        else [TRACKS[(index + run) % len(TRACKS)] for index in range(len(images))]
    )
    return [
        {
            "image": image,
            "track": track,
            "icon": to_emoji(track),
            "label": image_label(image),
        }
        for image, track in zip(images, tracks, strict=True)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("images", help="Print the matrix images as a JSON array.")
    distro = commands.add_parser(
        "distro", help="Print the distro a matrix image belongs to."
    )
    distro.add_argument(
        "--image", required=True, help="Matrix image, e.g. fedora:latest."
    )
    matrix = commands.add_parser(
        "matrix", help="Print {image, track} pairs for the workspace matrix."
    )
    matrix.add_argument(
        "--mode",
        required=True,
        choices=(*TRACKS, "rotate"),
        help="Pin every image to one track, or rotate the split by run parity.",
    )
    matrix.add_argument(
        "--run", required=True, type=int, help="Run number; its parity flips a rotate."
    )
    args = parser.parse_args(argv)

    if args.command in ("images", "matrix"):
        images = list(dev_runtime_images())
        if not images:
            print(
                f"{FILE_META_DISTROS} declares no dev runtime image; "
                "an empty matrix would skip every workspace job silently",
                file=sys.stderr,
            )
            return 1
        if args.command == "images":
            print(json.dumps(images))
        else:
            print(json.dumps(workspace_matrix(images, args.mode, args.run)))
        return 0

    print(distro_of_dev_runtime_image(args.image))
    return 0


if __name__ == "__main__":
    sys.exit(main())
