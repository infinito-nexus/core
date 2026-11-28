"""Write the deterministic facts of a changelog entry, or insert and lint one.

- ``facts`` writes ``jumps.md``, ``jumps.tsv``, ``contributors.md`` and
  ``contributors.tsv`` for ``<base>..<head>`` into ``--out``; the base is the
  newest ``vX.Y.Z`` tag before the head unless given.
- ``insert`` puts ``--entry`` into a copy of ``CHANGELOG.md`` under
  ``<out>/lint/`` and runs markdownlint-cli2 on it with the repository rules;
  its exit status is the linter's.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from cli import PROJECT_ROOT
from cli.contributing.changelog.extract import contributors, git, jumps
from cli.contributing.changelog.extract.entry import CONFIG, insert, lint
from utils.cache.files import read_text


def _gh_login(repository: str):
    def lookup(sha: str) -> str | None:
        result = subprocess.run(
            ["gh", "api", f"repos/{repository}/commits/{sha}", "--jq", ".author.login"],
            capture_output=True,
            text=True,
            check=False,
        )
        login = result.stdout.strip()
        return login if result.returncode == 0 and login not in {"", "null"} else None

    return lookup


def _facts(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    base = args.base or git.last_tag(repo, args.head)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    found = jumps.extract(repo, base, args.head)
    (out / "jumps.md").write_text(jumps.section(found, base), encoding="utf-8")
    (out / "jumps.tsv").write_text(
        "".join(f"{j.source}\t{j.name}\t{j.old or ''}\t{j.new}\n" for j in found),
        encoding="utf-8",
    )
    cache = Path(args.logins) if args.logins else None
    logins = contributors.read_logins(cache)
    if args.repository:
        logins = contributors.resolve_logins(
            repo, base, args.head, logins, _gh_login(args.repository)
        )
        if cache:
            cache.write_text(
                json.dumps(logins, indent=2, sort_keys=True), encoding="utf-8"
            )
    people = contributors.collect(repo, base, args.head, logins)
    (out / "contributors.md").write_text(contributors.section(people), encoding="utf-8")
    (out / "contributors.tsv").write_text(
        "".join(f"{p.name}\t{p.commits}\t{p.profile or ''}\n" for p in people),
        encoding="utf-8",
    )
    for person in people:
        if person.profile is None:
            print(f"no GitHub profile for {person.name}", file=sys.stderr)
    print(
        f"{base}..{args.head}: {len(found)} version jumps, {len(people)} contributors"
    )
    return 0


def _insert(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    scratch = Path(args.out) / "lint"
    scratch.mkdir(parents=True, exist_ok=True)
    changelog = read_text(str(repo / "CHANGELOG.md"))
    target = scratch / "CHANGELOG.md"
    target.write_text(insert(changelog, read_text(args.entry)), encoding="utf-8")
    result = lint(scratch, repo / CONFIG)
    sys.stdout.write(result.stdout + result.stderr)
    print(target)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cli.contributing.changelog.extract",
        description="Version jumps and contributors of a release, and its linted entry.",
    )
    parser.add_argument("--repo", default=str(PROJECT_ROOT), help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    facts = sub.add_parser("facts", help="write the version jumps and contributors")
    facts.add_argument("--head", required=True, help="target ref of the release")
    facts.add_argument("--base", help="base ref; the last vX.Y.Z tag when empty")
    facts.add_argument("--out", required=True, help="directory the files go to")
    facts.add_argument(
        "--repository", help="owner/name on GitHub; resolves missing logins via gh"
    )
    facts.add_argument("--logins", help="JSON cache of email to GitHub login")
    entry = sub.add_parser("insert", help="insert an entry into a scratch CHANGELOG.md")
    entry.add_argument("--entry", required=True, help="the entry Markdown file")
    entry.add_argument(
        "--out", required=True, help="directory the scratch copy goes to"
    )
    args = parser.parse_args(argv)
    if args.command == "facts":
        return _facts(args)
    return _insert(args)


if __name__ == "__main__":
    sys.exit(main())
