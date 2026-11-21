#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import gate, github

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .github import Gh

_SHA = re.compile(r"[0-9a-f]{40}")


def evaluate(
    gh: Gh, repo: str, sha: str, run_id: int, own_run_id: int, base: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """Judge the update pull request whose CI run *run_id* went green on *sha*.

    Args:
        gh: runs ``gh`` with the given arguments and returns its stdout.
        repo: ``owner/name``.
        sha: the head commit the run tested.
        run_id: the green ``🔀 Pull Request`` run of that commit.
        own_run_id: the run deciding the merge.
        base: the branch an update pull request must target.

    Returns:
        the pull request, ``None`` unless exactly one open pull request has
        that head, and the reasons refusing the merge, empty when it may
        merge. The stages run in order and stop at the first that refuses:
        pull request, checks, deployed roles.
    """
    prs = github.open_pull_requests(gh, repo, sha)
    if len(prs) != 1:
        return None, [f"{len(prs)} open pull requests have head {sha}, not one"]
    pr = prs[0]
    refusals = gate.pull_request_refusals(pr, repo, base)
    if refusals:
        return pr, refusals
    refusals = gate.check_refusals(
        github.check_runs(gh, repo, sha), github.statuses(gh, repo, sha), own_run_id
    )
    if refusals:
        return pr, refusals
    changed = gate.changed_roles(github.changed_paths(gh, repo, pr["number"]))
    csv_texts = github.role_runtime_csvs(gh, repo, run_id) if changed else []
    return pr, gate.role_refusals(changed, csv_texts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Decide whether an update pull request merges itself: a bot opened "
            "it, it carries the update label, every check on its head is green "
            "and CI deployed every role it changes."
        )
    )
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--sha", required=True, help="Head commit the CI run tested")
    parser.add_argument("--run-id", required=True, type=int, help="Green CI run id")
    parser.add_argument(
        "--own-run-id", required=True, type=int, help="Run id deciding the merge"
    )
    parser.add_argument("--base", required=True, help="Branch the PR must target")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="File the merge, pr and sha step outputs are appended to",
    )
    args = parser.parse_args(argv)
    if not _SHA.fullmatch(args.sha):
        parser.error(f"--sha is no full commit SHA: {args.sha!r}")

    pr, refusals = evaluate(
        github.run_gh, args.repo, args.sha, args.run_id, args.own_run_id, args.base
    )
    merge = pr is not None and not refusals
    label = f"#{pr['number']}" if pr is not None else args.sha
    if merge:
        print(f"{label} merges: checks green, every changed role deployed.")
    else:
        print(f"{label} stays open for a manual merge:")
        for reason in refusals:
            print(f"- {reason}")
    with args.output.open("a", encoding="utf-8") as handle:
        handle.write(f"merge={'true' if merge else 'false'}\n")
        if merge:
            handle.write(f"pr={pr['number']}\nsha={args.sha}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
