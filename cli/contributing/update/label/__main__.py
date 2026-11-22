#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from typing import TYPE_CHECKING
from urllib.parse import quote

from . import LEVELS, MAJOR, MINOR, PATCH, UPDATE

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from . import Label

GH_TIMEOUT_SECONDS = 120
_LEVEL_OF_UPDATE_TYPE = {
    "version-update:semver-major": MAJOR,
    "version-update:semver-minor": MINOR,
    "version-update:semver-patch": PATCH,
}
LEVEL_OF_NAME = {"major": MAJOR, "minor": MINOR, "patch": PATCH}


def level(update_type: str) -> Label:
    """The semver label of a Dependabot update.

    Args:
        update_type: the ``update-type`` output of ``dependabot/fetch-metadata``.

    Returns:
        ``minor`` or ``patch`` for those semver levels, ``major`` for everything
        else, so an update of unknown reach is never filed as a small one.
    """
    return _LEVEL_OF_UPDATE_TYPE.get(update_type.strip(), MAJOR)


def run_gh(args: Sequence[str]) -> str:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=GH_TIMEOUT_SECONDS,
    ).stdout


def names(gh: Callable[[Sequence[str]], str], path: str) -> set[str]:
    """The ``name`` of every label a paginated REST list returns.

    Args:
        gh: runs ``gh`` with the given arguments and returns its stdout.
        path: the REST path listing the labels.

    Returns:
        the label names.
    """
    out = gh(["api", "--paginate", path, "--jq", ".[].name"])
    return {line for line in out.splitlines() if line}


def ensure_labels(
    gh: Callable[[Sequence[str]], str], repo: str, labels: Iterable[Label]
) -> list[str]:
    """Create the labels the repository lacks, leaving existing ones untouched.

    Args:
        gh: runs ``gh`` with the given arguments and returns its stdout.
        repo: ``owner/name``.
        labels: the labels that must exist.

    Returns:
        the names created. A create that fails because a parallel run created
        the label first counts as done; any other failure raises.
    """
    existing = names(gh, f"repos/{repo}/labels")
    created: list[str] = []
    for label in labels:
        if label.name in existing:
            continue
        try:
            gh(
                [
                    "label",
                    "create",
                    label.name,
                    "--repo",
                    repo,
                    "--color",
                    label.color,
                    "--description",
                    label.description,
                ]
            )
        except subprocess.CalledProcessError:
            if label.name not in names(gh, f"repos/{repo}/labels"):
                raise
            continue
        created.append(label.name)
    return created


def sync(
    gh: Callable[[Sequence[str]], str], repo: str, pr: int, semver: Label
) -> list[str]:
    """Leave *pr* carrying the update label and exactly one semver label.

    Args:
        gh: runs ``gh`` with the given arguments and returns its stdout.
        repo: ``owner/name``.
        pr: the pull request number.
        semver: the semver label the pull request must carry.

    Returns:
        what was done, one line per action. A label the pull request already
        carries is not added again.
    """
    wanted = (UPDATE, semver)
    actions = [f"created label {name}" for name in ensure_labels(gh, repo, wanted)]
    current = names(gh, f"repos/{repo}/issues/{pr}/labels")
    for stale in LEVELS:
        if stale not in wanted and stale.name in current:
            gh(
                [
                    "api",
                    "--method",
                    "DELETE",
                    f"repos/{repo}/issues/{pr}/labels/{quote(stale.name)}",
                ]
            )
            actions.append(f"removed {stale.name}")
    missing = [label.name for label in wanted if label.name not in current]
    if missing:
        args = ["api", "--method", "POST", f"repos/{repo}/issues/{pr}/labels"]
        for name in missing:
            args += ["-f", f"labels[]={name}"]
        gh(args)
        actions.append(f"added {', '.join(missing)}")
    return actions


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            f"Label an update pull request `{UPDATE.name}` plus exactly one of "
            f"{', '.join(f'`{label.name}`' for label in LEVELS)}, creating "
            "labels the repository lacks."
        )
    )
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument(
        "--ensure-only",
        action="store_true",
        help="Only create the update labels the repository lacks",
    )
    parser.add_argument("--pr", type=int, help="Pull request number")
    parser.add_argument(
        "--update-type",
        help="update-type output of dependabot/fetch-metadata, possibly empty",
    )
    parser.add_argument(
        "--level",
        choices=sorted(LEVEL_OF_NAME),
        help="semver level utils.update.level printed for an updater pull request",
    )
    args = parser.parse_args(argv)
    if args.ensure_only:
        for name in ensure_labels(run_gh, args.repo, (UPDATE, *LEVELS)):
            print(f"created label {name}")
        return 0
    if args.pr is None or (args.update_type is None) == (args.level is None):
        parser.error(
            "--pr and exactly one of --update-type and --level are required "
            "without --ensure-only"
        )
    semver = (
        level(args.update_type) if args.level is None else LEVEL_OF_NAME[args.level]
    )
    actions = sync(run_gh, args.repo, args.pr, semver)
    for line in actions or [f"#{args.pr} already carries its labels"]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
