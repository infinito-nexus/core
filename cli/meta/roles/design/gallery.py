from __future__ import annotations

import argparse
import json
import sys

from utils.design.gallery import GALLERY_ROOT, app_gallery, gaps, manifest

_DESCRIPTION = """\
The screenshot gallery that make design-gallery captures, shared by the
designer and the tune-design companion.

commands:
  path      print the gallery directory of an app; make design-gallery copies
            its screenshots there
  manifest  print the captured views per side as <mode>-<viewport> shots and
            every view missing a shot another view of its side has, as JSON
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli.meta.roles.design.gallery",
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=("path", "manifest"))
    parser.add_argument("app", help="The application id, e.g. web-app-gitea.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        gallery = app_gallery(GALLERY_ROOT, args.app)
    except ValueError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2
    if args.command == "path":
        print(gallery)
        return 0
    shots = manifest(gallery)
    print(
        json.dumps(
            {"gallery": str(gallery), "manifest": shots, "gaps": gaps(shots)},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
