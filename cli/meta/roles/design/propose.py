from __future__ import annotations

import argparse
import sys

from utils.design.gallery import GALLERY_ROOT, app_gallery
from utils.design.proposal import file_proposal

_DESCRIPTION = """\
File a design proposal for an app into the design queue: it is written next to
the screenshots make design-gallery captured, and make design-queue lists the
role as proposed until the next full capture of the app replaces both.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli.meta.roles.design.propose",
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("app", help="The application id, e.g. web-app-gitea.")
    parser.add_argument(
        "--finding",
        action="append",
        required=True,
        help="One proposed design change; repeat it per change.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        print(file_proposal(app_gallery(GALLERY_ROOT, args.app), args.finding))
    except ValueError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
