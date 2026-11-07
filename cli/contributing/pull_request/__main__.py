"""Render a pull request body, or the GitHub web templates, from the one template.

Run via::

    python -m cli.contributing.pull_request render --values <file> [--output <file>]
    python -m cli.contributing.pull_request default [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli.contributing.pull_request.body import (
    TemplateError,
    generated,
    render,
    stale,
)
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cli.contributing.pull_request",
        description=(
            "Render a pull request body from .github/pull_request_template.md.j2, "
            "or write and check the GitHub web default rendered from it."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    body = commands.add_parser(
        "render", help="Render a body from a YAML or JSON values file."
    )
    body.add_argument(
        "--values",
        required=True,
        type=Path,
        help="YAML or JSON file with every template variable.",
    )
    body.add_argument(
        "--output", type=Path, help="Write the body here instead of stdout."
    )
    default = commands.add_parser(
        "default",
        help="Write the GitHub web templates: the chooser and one file per area.",
    )
    default.add_argument(
        "--check",
        action="store_true",
        help="Fail when a committed web template is not current.",
    )
    args = parser.parse_args(argv)

    if args.command == "render":
        return _render(args.values, args.output)
    if args.check:
        reasons = stale()
        for reason in reasons:
            print(
                f"[ERR] {reason}; run python -m cli.contributing.pull_request default",
                file=sys.stderr,
            )
        return 1 if reasons else 0
    for path, text in generated().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return 0


def _render(source: Path, output: Path | None) -> int:
    values = load_yaml_str(read_text(str(source)))
    if not isinstance(values, dict):
        print(
            f"[ERR] {source} must hold one mapping of template variables",
            file=sys.stderr,
        )
        return 1
    try:
        text = render(values)
    except TemplateError as error:
        print(f"[ERR] {error}", file=sys.stderr)
        return 1
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
