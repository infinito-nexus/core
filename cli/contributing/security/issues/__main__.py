#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from typing import TYPE_CHECKING, Any

from utils.cache.files import read_text

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

LABEL = "vulnerability"
LABEL_COLOR = "B60205"
LABEL_DESCRIPTION = "A pinned image carries a CVE at the scan threshold"
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
    return f"🛡️ {row['image']}"


def grouped(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Group the report rows by issue title."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(title(row), []).append(row)
    return groups


def body(rows: Sequence[Mapping[str, Any]]) -> str:
    """Render the issue body of one image, unsuppressed and CRITICAL rows first.

    A suppressed CVE stays listed with its ``suppressed_until`` day, so the
    issue remains open while the suppression runs. The table stops before
    the body would exceed ``BODY_LIMIT`` and names how many rows it left out.
    """
    first = rows[0]
    cves = {row["id"] for row in rows}
    suppressed = {row["id"] for row in rows if row["suppressed_until"]}
    head = [
        (
            f"`{first['image']}` carries {len(cves)} CVE(s) at the scan threshold, "
            f"{len(suppressed)} of them suppressed."
        ),
        "",
        f"Mirror: `{first['mirror']}@{first['digest']}`",
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
            f"{hidden} more row(s) are in the `vulnerability-findings` artifact of the scan run.",
        ]
    return "\n".join(head + shown + tail)


def sync(
    report: Mapping[str, Any], repo: str, gh: Callable[[Sequence[str]], str]
) -> list[str]:
    """Open, update and close one issue per image.

    Args:
        report: the ``make test-security`` report.
        repo: ``owner/name``.
        gh: runs ``gh`` with the given arguments and returns its stdout.

    Returns:
        What was done, one line per issue action; a ``failed`` line for a
        ``gh`` call that failed, while the other issues still run. At most
        one open issue per image survives, the others close as duplicates.
        An image whose CVE table changed gets a comment listing its
        unresolved CVEs and an updated body; an unchanged table leaves the
        issue alone. An issue is only closed when the scan reported no
        error, so an image that failed to scan keeps its issue open.
    """
    gh(
        [
            "label",
            "create",
            LABEL,
            "--repo",
            repo,
            "--color",
            LABEL_COLOR,
            "--description",
            LABEL_DESCRIPTION,
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
                LABEL,
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
    for name, rows in sorted(groups.items()):
        text = body(rows)
        issue = existing.get(name)
        if issue is None:
            args = [
                "issue",
                "create",
                "--repo",
                repo,
                "--title",
                name,
                "--label",
                LABEL,
                "--body",
                text,
            ]
            actions.append(attempt(gh, args, f"opened {name}"))
            continue
        number = str(issue["number"])
        if normalized(issue.get("body") or "") == normalized(text):
            actions.append(f"unchanged #{number} {name}")
            continue
        comment = [
            "issue",
            "comment",
            number,
            "--repo",
            repo,
            "--body",
            f"Still unresolved:\n\n{text}",
        ]
        actions.append(attempt(gh, comment, f"commented #{number} {name}"))
        edit = ["issue", "edit", number, "--repo", repo, "--body", text]
        actions.append(attempt(gh, edit, f"updated #{number} {name}"))
    if report["errors"]:
        return actions
    for name, issue in sorted(existing.items()):
        if name not in groups:
            args = [
                "issue",
                "close",
                str(issue["number"]),
                "--repo",
                repo,
                "--comment",
                "No engine reports a CVE at the threshold for this image any more.",
            ]
            actions.append(attempt(gh, args, f"closed #{issue['number']} {name}"))
    return actions


def normalized(text: str) -> str:
    return "\n".join(
        line.rstrip() for line in text.replace("\r\n", "\n").strip().splitlines()
    )


def attempt(gh: Callable[[Sequence[str]], str], args: Sequence[str], done: str) -> str:
    try:
        gh(args)
    except GH_FAILURES as exc:
        return f"failed {done}: {exc}"
    return done


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
    lines = sync(report, args.repo, run_gh)
    for line in lines:
        print(line)
    return 1 if any(line.startswith("failed ") for line in lines) else 0


if __name__ == "__main__":
    raise SystemExit(main())
