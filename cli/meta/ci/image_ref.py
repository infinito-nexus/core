"""Render a distro image reference from the ``meta/distros.yml`` SPOT.

Exists so shell and workflow steps can compose the same reference the env
layer composes, instead of spelling ``ghcr.io/...`` out a second time.

    python3 -m cli.meta.ci.image_ref --kind environment \\
        --distro debian --owner acme --repository infinito-nexus --tag ci-abc
"""

from __future__ import annotations

import argparse
import sys

from utils.distros import (
    IMAGE_ENVIRONMENT,
    IMAGE_PKGMGR,
    environment_image,
    pkgmgr_image,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        required=True,
        choices=(IMAGE_PKGMGR, IMAGE_ENVIRONMENT),
        help="Which image reference to render.",
    )
    parser.add_argument("--distro", required=True, help="Distro id, e.g. debian.")
    parser.add_argument("--owner", required=True, help="Registry owner.")
    parser.add_argument("--tag", required=True, help="Image tag.")
    parser.add_argument(
        "--repository",
        default="",
        help="Repository name; required for --kind environment.",
    )
    args = parser.parse_args(argv)

    if args.kind == IMAGE_PKGMGR:
        print(pkgmgr_image(args.distro, owner=args.owner, tag=args.tag))
        return 0

    if not args.repository:
        parser.error("--repository is required for --kind environment")
    print(
        environment_image(
            args.distro,
            owner=args.owner,
            repository=args.repository,
            tag=args.tag,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
