"""Serve the editable bond matrix, or export it as a static file."""

from __future__ import annotations

import argparse
import contextlib
import shutil
import subprocess
import sys
from pathlib import Path

from utils import PROJECT_ROOT

from .matrix import collect_edges, participants
from .render import render, render_json
from .serve import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bond",
        description=(
            "Show which roles bond to which, and how tightly. Serves an editable "
            "matrix on localhost; a cell edit rewrites the bond in the role."
        ),
    )
    parser.add_argument(
        "--roles-dir",
        default=str(PROJECT_ROOT / "roles"),
        help="roles directory to read and write (default: the project's own)",
    )
    parser.add_argument(
        "-o",
        "--out",
        default="",
        help="export a read-only file here instead of serving",
    )
    parser.add_argument(
        "--format",
        choices=("html", "json"),
        default="html",
        help="export format, json implies --out (default: html)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="port to serve on (default: any free port)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="do not open a browser",
    )
    return parser


def _open(target: str) -> None:
    """Open the matrix with the desktop's handler, if there is one."""
    opener = shutil.which("xdg-open") or shutil.which("open")
    if not opener:
        print(f"no xdg-open/open on PATH; the matrix is at {target}", file=sys.stderr)
        return
    subprocess.run([opener, target], check=False)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roles_dir = Path(args.roles_dir)
    if not roles_dir.is_dir():
        print(f"no such roles directory: {roles_dir}", file=sys.stderr)
        return 2

    edges = collect_edges(roles_dir)
    if not edges:
        print(f"no services.<key>.bond found under {roles_dir}", file=sys.stderr)
        return 1

    if args.format == "json":
        payload = render_json(edges)
        if not args.out:
            print(payload)
            return 0
    elif args.out:
        payload = render(edges, participants(edges))
    else:
        httpd, url = serve(roles_dir, edges, args.port)
        print(f"{url}  ({len(edges)} bonds, editing writes to {roles_dir})")
        if not args.no_open:
            _open(url)
        with contextlib.suppress(KeyboardInterrupt), httpd:
            httpd.serve_forever()
        return 0

    Path(args.out).write_text(payload, encoding="utf-8")
    print(args.out)
    return 0
