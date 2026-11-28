"""Deterministic steps of the release announcements, for a run by hand.

- ``brief`` writes ``brief.yml`` from the ``CHANGELOG.md`` entries since the
  last ``vX.Y.Z`` tag.
- ``outline`` writes ``investor-outline.yml``, the investor sections the brief
  and the optional facts file prove.
- ``check`` checks ``brief.yml`` and every channel text in the directory and
  exits 1 on any finding.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from agents.routines.tools import release
from cli import PROJECT_ROOT
from cli.contributing.changelog.archive.changelog_md import split_into_entries
from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml, load_yaml_any

BRIEF = "brief.yml"
OUTLINE = "investor-outline.yml"


def _tags(repo: Path) -> set[str]:
    output = subprocess.run(
        ["git", "tag", "--list", "v*"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return set(output.split())


def _facts(path: str | None) -> tuple[dict, str]:
    if not path:
        return {}, ""
    return load_yaml_any(path) or {}, read_text(path)


def _brief(args: argparse.Namespace) -> int:
    out = Path(args.dir)
    target = out / BRIEF
    if target.exists():
        print(f"{target} exists; remove it to start the brief over", file=sys.stderr)
        return 1
    entries, _ = split_into_entries(read_text(args.changelog))
    tags = _tags(Path(args.repo))
    picked = release.since_last_tag(entries, args.version, tags)
    base = release.base_of(entries, args.version, tags)
    dump_yaml(target, release.skeleton(picked, base))
    print(target)
    return 0


def _outline(args: argparse.Namespace) -> int:
    out = Path(args.dir)
    facts, _ = _facts(args.facts)
    titles = release.outline(load_yaml_any(str(out / BRIEF)), facts)
    dump_yaml(out / OUTLINE, titles)
    print("\n".join(titles))
    return 0


def _check(args: argparse.Namespace) -> int:
    out = Path(args.dir)
    brief_text = read_text(str(out / BRIEF))
    brief = load_yaml_any(str(out / BRIEF))
    facts, facts_text = _facts(args.facts)
    files = {
        path.name: read_text(str(path))
        for path in sorted(out.iterdir())
        if path.is_file() and path.suffix in release.TEXT_SUFFIXES
    }
    found = release.brief_problems(brief) + release.problems(
        files, brief, brief_text + "\n" + facts_text, release.outline(brief, facts)
    )
    print("\n".join(found) if found else f"{len(files)} channel files clean")
    return 1 if found else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cli.contributing.release",
        description="Brief, investor outline and check of the release announcements.",
    )
    parser.add_argument("--repo", default=str(PROJECT_ROOT), help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    brief = sub.add_parser("brief", help="write brief.yml from the changelog")
    brief.add_argument("--version", required=True, help="release version, no v")
    brief.add_argument(
        "--changelog",
        default=str(PROJECT_ROOT / "CHANGELOG.md"),
        help="changelog to read; the scratch copy before the release is tagged",
    )
    brief.add_argument("--dir", required=True, help="the release directory")
    for name, text in (
        ("outline", "write the investor sections the evidence proves"),
        ("check", "check brief.yml and every channel text"),
    ):
        step = sub.add_parser(name, help=text)
        step.add_argument("--dir", required=True, help="the release directory")
        step.add_argument("--facts", help="the operator's investor facts YAML")
    args = parser.parse_args(argv)
    handlers = {"brief": _brief, "outline": _outline, "check": _check}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
