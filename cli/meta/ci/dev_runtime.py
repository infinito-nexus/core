"""Answer the development-runtime matrix questions from the distro SPOT.

Exists so workflow steps can ask for the matrix, and for the distro behind a
matrix entry, without embedding a python one-liner per question.

    python3 -m cli.meta.ci.dev_runtime images
    python3 -m cli.meta.ci.dev_runtime distro --image fedora:latest
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
    args = parser.parse_args(argv)

    if args.command == "images":
        images = list(dev_runtime_images())
        if not images:
            print(
                f"{FILE_META_DISTROS} declares no dev runtime image; "
                "an empty matrix would skip every workspace job silently",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(images))
        return 0

    print(distro_of_dev_runtime_image(args.image))
    return 0


if __name__ == "__main__":
    sys.exit(main())
