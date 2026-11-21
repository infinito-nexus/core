"""Args:
resolve REF: print the full commit REF names; refuse a ref that is no commit.
read: print the pinned commit; fail loudly while no pin exists.
declare SHA: pin SHA and remove the checkouts of every commit but SHA and the previous pin.
applied [SHA]: record SHA as applied, or print the commit last applied.
declarations: print this checkout's cache repositories, hosts and artefacts as JSON.
env: print the declaration-derived .env keys of this checkout.
drift DIR: name every declaration of this checkout that differs from the checkout in DIR.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from utils.cache import PROJECT_ROOT, pin
from utils.cache.artefacts import artefacts
from utils.cache.hosts import host_records, repo_records
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache import hosts, tls, upstreams
from utils.env.parser import parse_static_env_with_comments

DERIVED = (hosts, tls, upstreams)
PREFIX = "[cache-pin]"


def _declarations() -> dict:
    return {
        "repos": repo_records(),
        "hosts": host_records(),
        pin.ARTEFACTS: {item.name: dataclasses.asdict(item) for item in artefacts()},
    }


def _derived_env() -> list[str]:
    static, comments = parse_static_env_with_comments(PROJECT_ROOT / "default.env")
    ctx = BuildContext(
        static=static,
        static_comments=comments,
        repo_root=PROJECT_ROOT,
        on_gha=False,
        on_act=False,
    )
    eb = EnvBuilder()
    for handler in DERIVED:
        handler.apply(eb, ctx)
    return [f"{handler.KEY}={eb.values.get(handler.KEY, '')}" for handler in DERIVED]


def _drift(directory: Path) -> int:
    own = json.loads(json.dumps(_declarations(), sort_keys=True))
    lines = pin.drift(own, pin.pinned_declarations(directory))
    if lines:
        print(
            f"{PREFIX} this checkout's cache: declarations differ from the pinned "
            f"commit ({directory}); they are not applied, {pin.BUMP_HINT}:",
            file=sys.stderr,
        )
        for line in lines:
            print(f"{PREFIX}   {line}", file=sys.stderr)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m cli.meta.cache.pin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("resolve").add_argument("ref")
    sub.add_parser("read")
    sub.add_parser("declare").add_argument("sha")
    sub.add_parser("applied").add_argument("sha", nargs="?", default="")
    sub.add_parser("declarations")
    sub.add_parser("env")
    sub.add_parser("drift").add_argument("directory", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "resolve":
            print(pin.resolve(args.ref, Path.cwd()))
        elif args.command == "read":
            print(pin.read(pin.env_path(pin.PIN_FILE_KEY)))
        elif args.command == "declare":
            removed = pin.declare(
                pin.env_path(pin.PIN_FILE_KEY),
                pin.env_path(pin.PIN_ROOT_KEY),
                args.sha,
            )
            for path in removed:
                print(f"{PREFIX} pruned the earlier checkout {path}", file=sys.stderr)
            print(args.sha)
        elif args.command == "applied":
            path = pin.env_path(pin.PIN_FILE_KEY)
            if args.sha:
                pin.write_applied(path, args.sha)
            else:
                print(pin.read_applied(path) or "none")
        elif args.command == "declarations":
            print(json.dumps(_declarations(), sort_keys=True))
        elif args.command == "env":
            print("\n".join(_derived_env()))
        else:
            return _drift(args.directory)
    except pin.PinError as exc:
        print(f"{PREFIX} {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
