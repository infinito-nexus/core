from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from cli.contributing.role.skeleton.manifest import fields, validate
from cli.contributing.role.skeleton.render import RenderError, render
from utils.cache.yaml import load_yaml_str

EXIT_INVALID = 2


def _parse(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError:
        return load_yaml_str(text)


def _fail(errors: list[str]) -> int:
    for error in errors:
        print(" ".join(error.split()), file=sys.stderr)
    return EXIT_INVALID


def _render(target: Path, force: bool) -> int:
    try:
        data = _parse(sys.stdin.read())
    except yaml.YAMLError as exc:
        return _fail([f"manifest: is neither JSON nor YAML: {exc}"])
    manifest, errors = validate(data)
    if manifest is None:
        return _fail(errors)
    try:
        role_dir = render(manifest, target, force=force)
    except RenderError as exc:
        return _fail(exc.errors)
    print(role_dir)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cli contributing role skeleton",
        description=(
            "Render a custom web-app-cst-<name> role from a short manifest: "
            "schema prints the manifest fields as JSON, render reads a JSON or "
            "YAML manifest from stdin and writes the role."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="print every manifest field as JSON")
    render_parser = commands.add_parser(
        "render",
        help="write <target>/web-app-cst-<name>/ from the manifest on stdin",
    )
    render_parser.add_argument(
        "--target",
        required=True,
        type=Path,
        help="directory the role directory is written into",
    )
    render_parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing role directory",
    )
    args = parser.parse_args(argv)
    if args.command == "schema":
        print(json.dumps([item.as_json() for item in fields()], indent=2))
        return 0
    return _render(args.target, args.force)


if __name__ == "__main__":
    sys.exit(main())
