"""Decide whether an update pull request has earned an automatic merge.

Each check returns the reasons that refuse the merge; an empty list passes it.
"""

from __future__ import annotations

import csv
import io
import re
from typing import TYPE_CHECKING, Any

from cli.contributing.update.label import UPDATE

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

BOT_BRANCH_PREFIXES = {
    "infinito-nexus-updater[bot]": "update/",
    "dependabot[bot]": "dependabot/",
}
GREEN_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})
ROLE_COLUMN = "role"
_ROLE_PATH = re.compile(r"^roles/(?P<role>[^/]+)/")


def pull_request_refusals(pr: Mapping[str, Any], repo: str, base: str) -> list[str]:
    """Why *pr* is no update pull request a bot may merge.

    Args:
        pr: the pull request as the REST API returns it.
        repo: ``owner/name`` the head branch must live in.
        base: the branch the pull request must target.

    Returns:
        one line per unmet condition: an author outside the update bots, a
        head branch outside that bot's prefix or repository, a draft, another
        base branch, a missing ``update`` label.
    """
    refusals: list[str] = []
    author = pr["user"]["login"]
    head = pr["head"]["ref"]
    prefix = BOT_BRANCH_PREFIXES.get(author)
    if prefix is None:
        refusals.append(f"author {author} is no update bot")
    elif not head.startswith(prefix):
        refusals.append(f"branch {head} lacks the {prefix} prefix of {author}")
    head_repo = pr["head"]["repo"]
    if head_repo is None or head_repo["full_name"] != repo:
        refusals.append(f"head branch {head} lives outside {repo}")
    if pr["draft"]:
        refusals.append("pull request is a draft")
    if pr["base"]["ref"] != base:
        refusals.append(f"base branch is {pr['base']['ref']}, not {base}")
    if UPDATE.name not in {label["name"] for label in pr["labels"]}:
        refusals.append(f"label {UPDATE.name} is missing")
    return refusals


def check_refusals(
    check_runs: Iterable[Mapping[str, Any]],
    statuses: Iterable[Mapping[str, Any]],
    own_run_id: int,
) -> list[str]:
    """Why the checks on the head commit are not all green.

    Args:
        check_runs: the commit's latest check runs, each with ``name``,
            ``status``, ``conclusion`` and ``details_url``.
        statuses: the commit's latest status per context, each with
            ``context`` and ``state``.
        own_run_id: the run deciding the merge; its own check runs are still
            in progress and do not count.

    Returns:
        one line per check run that has not completed as success, skipped or
        neutral, one per status that is not success, and one when no check
        run is left to judge.
    """
    own = f"/actions/runs/{own_run_id}/"
    refusals: list[str] = []
    judged = 0
    for run in check_runs:
        if own in (run["details_url"] or ""):
            continue
        judged += 1
        if run["status"] != "completed":
            refusals.append(f"check {run['name']} is {run['status']}")
        elif run["conclusion"] not in GREEN_CONCLUSIONS:
            refusals.append(f"check {run['name']} concluded {run['conclusion']}")
    if not judged:
        refusals.append("no check run on the head commit")
    refusals.extend(
        f"status {status['context']} is {status['state']}"
        for status in statuses
        if status["state"] != "success"
    )
    return refusals


def changed_roles(paths: Iterable[str]) -> set[str]:
    """The roles whose files *paths* touch.

    Args:
        paths: repository-relative paths, old names of renamed files included.

    Returns:
        ``<name>`` of every ``roles/<name>/...`` path.
    """
    return {match["role"] for path in paths if (match := _ROLE_PATH.match(path))}


def deployed_roles(csv_texts: Iterable[str]) -> set[str]:
    """The roles the deploy rows ran, read from ``role-runtimes-*`` CSVs.

    The CSVs come out of a pull request's CI run, so they are parsed as data
    and their values only ever compared, never executed or used as paths.

    Args:
        csv_texts: the text of each CSV ``cli.meta.ci.roles.runtime`` wrote.

    Returns:
        every non-empty value of the ``role`` column, dependencies included.
    """
    roles: set[str] = set()
    for text in csv_texts:
        for row in csv.DictReader(io.StringIO(text)):
            role = (row.get(ROLE_COLUMN) or "").strip()
            if role:
                roles.add(role)
    return roles


def role_refusals(changed: set[str], csv_texts: list[str]) -> list[str]:
    """Why the deploy rows do not prove every changed role.

    Args:
        changed: the roles the pull request changes.
        csv_texts: the ``role-runtimes-*`` CSVs of the pull request's CI run.

    Returns:
        nothing when no role changed; one line when no CSV was uploaded,
        since an upload that found no file is silent; otherwise one line per
        changed role no deploy row ran.
    """
    if not changed:
        return []
    if not csv_texts:
        return [f"no role-runtimes artifact proves {', '.join(sorted(changed))}"]
    deployed = deployed_roles(csv_texts)
    return [
        f"role {role} changed, but no deploy row ran it"
        for role in sorted(changed - deployed)
    ]
