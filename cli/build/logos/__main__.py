from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.design.branding import DESIGN_ROLE
from utils.design.preview import build_preview, design_roles
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cli.build.logos",
        description="Render every app's branding assets from one logo and base color into an HTML preview.",
    )
    p.add_argument(
        "--domain",
        required=True,
        help="primary domain the role domains are rendered with",
    )
    p.add_argument(
        "--logo", default="", help="logo file; web-svc-design's logo when empty"
    )
    p.add_argument(
        "--base", default="", help="hex base color; web-svc-design's base when empty"
    )
    p.add_argument(
        "--roles",
        default="",
        help="comma-separated application ids; every role with a design entry when empty",
    )
    p.add_argument(
        "--out", required=True, help="output directory for the assets and index.html"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    design = load_yaml_any(
        str(PROJECT_ROOT / "roles" / DESIGN_ROLE / ROLE_FILE_META_SERVICES)
    )["design"]
    logo = Path(args.logo or design["logo"])
    logo = (
        logo
        if logo.is_absolute()
        else (Path.cwd() / logo if args.logo else PROJECT_ROOT / logo)
    )
    if not logo.is_file():
        print(f"logo not found: {logo}", file=sys.stderr)
        return 2
    roles = [
        role.strip() for role in args.roles.split(",") if role.strip()
    ] or design_roles(PROJECT_ROOT / "roles")
    index = build_preview(
        str(logo.resolve()),
        args.base or design["colors"]["base"],
        args.domain,
        roles,
        Path(args.out),
        PROJECT_ROOT,
    )
    print(index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
