#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import TYPE_CHECKING, Any, NamedTuple

from utils.cache.files import read_text
from utils.docker.image.discovery import split_name_and_suffix
from utils.security.pipeline import pipeline

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence


class Tracker(NamedTuple):
    """One family of vulnerability issues, owned by one label.

    Args:
        label: the label every issue of the family carries; a sync lists,
            updates and closes only issues of this label.
        color: the label colour.
        description: the label description.
        source: renders the line under the head line from the first row.
        artifact: where the rows the body leaves out are kept.
        gone: the comment an issue closes with.
        covers: ``(report, title) -> bool``, whether the report speaks for
            the issue of that title, so its absence may close it.
        live: ``report -> titles``, every image the report still scans or
            a role still pins, scanned clean or not, so its issue never
            closes as superseded; ``None`` when the report cannot tell,
            which supersedes nothing.
    """

    label: str
    color: str
    description: str
    source: Callable[[Mapping[str, Any]], str]
    artifact: str
    gone: str
    covers: Callable[[Mapping[str, Any], str], bool]
    live: Callable[[Mapping[str, Any]], Collection[str] | None]


def pinned(report: Mapping[str, Any]) -> set[str]:
    """
    Args:
        report: carries ``pinned``, the image reference every role pins.

    Returns:
        The issue title of every pinned image.
    """
    return {title({"image": image}) for image in report["pinned"]}


LABEL = "vulnerability"
LABEL_COLOR = "B60205"
LABEL_DESCRIPTION = "A pinned image carries a CVE at the scan threshold"
MIRROR = Tracker(
    label=LABEL,
    color=LABEL_COLOR,
    description=LABEL_DESCRIPTION,
    source=lambda row: f"Mirror: `{row['mirror']}@{row['digest']}`",
    artifact="the `vulnerability-findings` artifact of the scan run",
    gone="No engine reports a CVE at the threshold for this image any more.",
    covers=lambda report, _title: not report["errors"],
    live=pinned,
)
MARK = "🛡️ "
SUPERSEDED = "Superseded by {by}: this run no longer scans this tag."
ISSUE_URL = re.compile(r"/issues/(?P<number>\d+)$")
ISSUE_LIMIT = "1000"
GH_TIMEOUT_SECONDS = 120
GH_FAILURES = (subprocess.CalledProcessError, subprocess.TimeoutExpired)
COLUMNS = (
    "id",
    "severity",
    "engine",
    "role",
    "service",
    "package",
    "installed",
    "fixed",
    "suppressed_until",
)
BODY_LIMIT = 60000


def title(row: Mapping[str, Any]) -> str:
    """Return the stable issue title of one image."""
    return f"{MARK}{row['image']}"


def image_repository(image: str) -> tuple[str, str]:
    """
    Args:
        image: ``[registry[:port]/]repository[:tag][@digest]``.

    Returns:
        ``(repository, tag)``: the repository keeps its registry host and
        port, a digest is dropped, and an image without a tag is ``latest``.
    """
    base, suffix = split_name_and_suffix(image.split("@", 1)[0])
    return base, suffix.removeprefix(":") or "latest"


def repository_of(name: str) -> str:
    """Return the image repository an issue title of :func:`title` names."""
    return image_repository(name.removeprefix(MARK))[0]


def superseded(
    titles: Iterable[str],
    standing: Mapping[str, str],
    live: Collection[str],
) -> dict[str, str]:
    """
    Args:
        titles: the titles of the open issues.
        standing: by title, every image the report files or scans clean,
            mapped to how a comment names it.
        live: the titles of every image the report still scans or a role
            still pins.

    Returns:
        By title, every open issue titled by :func:`title` with another tag
        of a standing image's repository whose title is not live, mapped
        to the names of the standing images of that repository.
    """
    current: dict[str, dict[str, str]] = {}
    for name, named in standing.items():
        repository, tag = image_repository(name.removeprefix(MARK))
        current.setdefault(repository, {})[tag] = named
    replaced = {}
    for name in titles:
        repository, tag = image_repository(name.removeprefix(MARK))
        if not name.startswith(MARK) or name in live or repository not in current:
            continue
        if tag not in current[repository]:
            replaced[name] = ", ".join(current[repository].values())
    return replaced


def grouped(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Group the report rows by issue title."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(title(row), []).append(row)
    return groups


def severity_counts(rows: Iterable[Mapping[str, Any]]) -> str:
    """Return the distinct CVE count per severity, e.g. ``CRITICAL 7, HIGH 42``."""
    cves: dict[str, set[str]] = {}
    for row in rows:
        cves.setdefault(row["severity"], set()).add(row["id"])
    order = pipeline().SEVERITIES
    ranked = sorted(
        cves,
        key=lambda s: (order.index(s) if s in order else len(order), s),
    )
    return ", ".join(f"{severity} {len(cves[severity])}" for severity in ranked)


def body(rows: Sequence[Mapping[str, Any]], tracker: Tracker) -> str:
    """Render the issue body of one image, unsuppressed and CRITICAL rows first.

    A suppressed CVE stays listed with its ``suppressed_until`` day, so the
    issue remains open while the suppression runs. The head line ends in
    :func:`severity_counts`. The table stops before the body would exceed
    ``BODY_LIMIT`` and names how many rows it left out.
    """
    first = rows[0]
    cves = {row["id"] for row in rows}
    suppressed = {row["id"] for row in rows if row["suppressed_until"]}
    head = [
        (
            f"`{first['image']}` carries {len(cves)} CVE(s) at the scan threshold, "
            f"{len(suppressed)} of them suppressed: {severity_counts(rows)}."
        ),
        "",
        tracker.source(first),
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    tail = [
        "",
        (
            "Suppress a CVE in the owning role's `meta/services.yml` under "
            "`<service>.security.suppressions`, see "
            "`docs/contributing/actions/testing/suppression.md`."
        ),
    ]
    table = [
        "| " + " | ".join(str(row[column] or "-") for column in COLUMNS) + " |"
        for row in sorted(
            rows,
            key=lambda r: (
                r["suppressed_until"] is not None,
                r["severity"] != "CRITICAL",
                *(str(r[c]) for c in COLUMNS),
            ),
        )
    ]
    budget = BODY_LIMIT - len("\n".join(head + tail)) - 200
    shown = []
    for line in table:
        budget -= len(line) + 1
        if budget < 0:
            break
        shown.append(line)
    hidden = len(table) - len(shown)
    if hidden:
        shown += [
            "",
            f"{hidden} more row(s) are in {tracker.artifact}.",
        ]
    return "\n".join(head + shown + tail)


def sync(
    report: Mapping[str, Any],
    repo: str,
    gh: Callable[[Sequence[str]], str],
    tracker: Tracker,
) -> list[str]:
    """Open, update and close one issue per image.

    Args:
        report: ``findings`` (the rows) and ``errors``, plus whatever
            ``tracker.covers`` and ``tracker.live`` read.
        repo: ``owner/name``.
        gh: runs ``gh`` with the given arguments and returns its stdout.
        tracker: the issue family; only issues of its label are touched.

    Returns:
        What was done, one line per issue action; a ``failed`` line for a
        ``gh`` call that failed, while the other issues still run. At most
        one open issue per image survives, the others close as duplicates.
        An image whose CVE table changed gets a comment listing its
        unresolved CVEs and an updated body; an unchanged table leaves the
        issue alone. An issue :func:`superseded` names closes naming its
        standing issue. Any other issue without rows closes only when
        ``tracker.covers`` says the report speaks for it and every image of
        its repository with rows has a standing issue.
    """
    gh(
        [
            "label",
            "create",
            tracker.label,
            "--repo",
            repo,
            "--color",
            tracker.color,
            "--description",
            tracker.description,
            "--force",
        ]
    )
    issues = json.loads(
        gh(
            [
                "issue",
                "list",
                "--repo",
                repo,
                "--label",
                tracker.label,
                "--state",
                "open",
                "--json",
                "number,title,body",
                "--limit",
                ISSUE_LIMIT,
            ]
        )
    )
    actions = []
    existing: dict[str, Mapping[str, Any]] = {}
    for issue in sorted(issues, key=lambda issue: issue["number"]):
        kept = existing.setdefault(issue["title"], issue)
        if kept is not issue:
            args = [
                "issue",
                "close",
                str(issue["number"]),
                "--repo",
                repo,
                "--comment",
                f"Duplicate of #{kept['number']}: one issue per image.",
            ]
            actions.append(
                attempt(
                    gh, args, f"closed duplicate #{issue['number']} {issue['title']}"
                )
            )
    groups = grouped(report["findings"])
    filed: dict[str, str] = {}
    for name, rows in sorted(groups.items()):
        done, number = filed_issue(gh, repo, tracker, name, rows, existing.get(name))
        actions += done
        if number is not None:
            filed[name] = f"#{number} {name}"
    replaced = replacements(report, tracker, existing, groups, filed)
    unfiled = {repository_of(name) for name in groups if name not in filed}
    for name, issue in sorted(existing.items()):
        if name in replaced:
            comment, done = SUPERSEDED.format(by=replaced[name]), "closed superseded"
        elif (
            name not in groups
            and repository_of(name) not in unfiled
            and tracker.covers(report, name)
        ):
            comment, done = tracker.gone, "closed"
        else:
            continue
        number = str(issue["number"])
        args = ["issue", "close", number, "--repo", repo, "--comment", comment]
        actions.append(attempt(gh, args, f"{done} #{number} {name}"))
    return actions


def replacements(
    report: Mapping[str, Any],
    tracker: Tracker,
    titles: Iterable[str],
    groups: Collection[str],
    filed: Mapping[str, str],
) -> dict[str, str]:
    """
    Args:
        report: the report of the sync.
        tracker: the issue family.
        titles: the titles of the open issues.
        groups: the titles of every image with rows.
        filed: ``#number title`` of every image whose issue stands, by title.

    Returns:
        :func:`superseded` over the filed images and the live ones the
        report scans clean, nothing when ``tracker.live`` cannot tell.
    """
    known = tracker.live(report)
    if known is None:
        return {}
    live = {*known, *groups}
    clean = {
        name: name
        for name in sorted(live - set(groups))
        if tracker.covers(report, name)
    }
    return superseded(titles, {**filed, **clean}, live)


def filed_issue(
    gh: Callable[[Sequence[str]], str],
    repo: str,
    tracker: Tracker,
    name: str,
    rows: Sequence[Mapping[str, Any]],
    issue: Mapping[str, Any] | None,
) -> tuple[list[str], str | None]:
    """
    Args:
        gh: runs ``gh`` with the given arguments and returns its stdout.
        repo: ``owner/name``.
        tracker: the issue family.
        name: the issue title of the image.
        rows: the report rows of the image.
        issue: the open issue of that title, ``None`` when there is none.

    Returns:
        ``(actions, number)``: what was done, and the number of the issue
        that stands for the image afterwards, ``None`` when a ``gh`` call
        failed or ``gh`` printed no issue URL.
    """
    text = body(rows, tracker)
    if issue is None:
        args = [
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            name,
            "--label",
            tracker.label,
            "--body",
            text,
        ]
        action, out = called(gh, args, f"opened {name}")
        created = None if out is None else ISSUE_URL.search(out.strip())
        return [action], None if created is None else created["number"]
    number = str(issue["number"])
    if normalized(issue.get("body") or "") == normalized(text):
        return [f"unchanged #{number} {name}"], number
    comment = [
        "issue",
        "comment",
        number,
        "--repo",
        repo,
        "--body",
        f"Still unresolved:\n\n{text}",
    ]
    edit = ["issue", "edit", number, "--repo", repo, "--body", text]
    done = [
        attempt(gh, comment, f"commented #{number} {name}"),
        attempt(gh, edit, f"updated #{number} {name}"),
    ]
    return done, None if any(line.startswith("failed ") for line in done) else number


def normalized(text: str) -> str:
    return "\n".join(
        line.rstrip() for line in text.replace("\r\n", "\n").strip().splitlines()
    )


def called(
    gh: Callable[[Sequence[str]], str], args: Sequence[str], done: str
) -> tuple[str, str | None]:
    """
    Returns:
        ``(action, stdout)``: *done* and what ``gh`` printed, or a
        ``failed`` line and ``None`` when the call failed.
    """
    try:
        out = gh(args)
    except GH_FAILURES as exc:
        return f"failed {done}: {exc}", None
    return done, out


def attempt(gh: Callable[[Sequence[str]], str], args: Sequence[str], done: str) -> str:
    return called(gh, args, done)[0]


def run_gh(args: Sequence[str]) -> str:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=GH_TIMEOUT_SECONDS,
    ).stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Mirror the make test-security report into GitHub issues."
    )
    parser.add_argument("--report", required=True, help="The make test-security report")
    parser.add_argument("--repo", required=True, help="owner/name")
    args = parser.parse_args(argv)
    report = json.loads(read_text(args.report))
    lines = sync(report, args.repo, run_gh, MIRROR)
    for line in lines:
        print(line)
    return 1 if any(line.startswith("failed ") for line in lines) else 0


if __name__ == "__main__":
    raise SystemExit(main())
