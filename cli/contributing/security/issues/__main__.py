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
COLUMNS = ("engine", "role", "service", "package", "installed", "fixed", "severity")


def title(row: Mapping[str, Any]) -> str:
    """Return the stable issue title of one CVE in one image."""
    return f"🛡️ {row['id']} in {row['image']}"


def grouped(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Group the report rows by issue title."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(title(row), []).append(row)
    return groups


def body(rows: Sequence[Mapping[str, Any]]) -> str:
    """Render the issue body of one CVE in one image."""
    first = rows[0]
    lines = [
        f"`{first['id']}` ({', '.join(first['ids'])}) in `{first['image']}`.",
        "",
        f"Mirror: `{first['mirror']}@{first['digest']}`",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    lines.extend(
        "| " + " | ".join(str(row[column]) or "-" for column in COLUMNS) + " |"
        for row in sorted(rows, key=lambda r: tuple(str(r[c]) for c in COLUMNS))
    )
    lines += [
        "",
        (
            "Suppress it in the owning role's `meta/services.yml` under "
            "`<service>.security.suppressions`, see "
            "`docs/contributing/actions/testing/suppression.md`."
        ),
    ]
    return "\n".join(lines)


def sync(
    report: Mapping[str, Any], repo: str, gh: Callable[[Sequence[str]], str]
) -> list[str]:
    """Open, update and close one issue per CVE and image.

    Args:
        report: the ``make test-security`` report.
        repo: ``owner/name``.
        gh: runs ``gh`` with the given arguments and returns its stdout.

    Returns:
        What was done, one line per issue. An issue is only closed when the
        scan reported no error, so an image that failed to scan keeps its
        issues open.
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
    existing = {
        issue["title"]: issue["number"]
        for issue in json.loads(
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
                    "number,title",
                    "--limit",
                    ISSUE_LIMIT,
                ]
            )
        )
    }
    actions = []
    groups = grouped(report["findings"])
    for name, rows in sorted(groups.items()):
        if name in existing:
            gh(
                [
                    "issue",
                    "edit",
                    str(existing[name]),
                    "--repo",
                    repo,
                    "--body",
                    body(rows),
                ]
            )
            actions.append(f"updated #{existing[name]} {name}")
        else:
            gh(
                [
                    "issue",
                    "create",
                    "--repo",
                    repo,
                    "--title",
                    name,
                    "--label",
                    LABEL,
                    "--body",
                    body(rows),
                ]
            )
            actions.append(f"opened {name}")
    if report["errors"]:
        return actions
    for name, number in sorted(existing.items()):
        if name not in groups:
            gh(
                [
                    "issue",
                    "close",
                    str(number),
                    "--repo",
                    repo,
                    "--comment",
                    "No engine reports it at the threshold any more.",
                ]
            )
            actions.append(f"closed #{number} {name}")
    return actions


def run_gh(args: Sequence[str]) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True
    ).stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Mirror the make test-security report into GitHub issues."
    )
    parser.add_argument("--report", required=True, help="The make test-security report")
    parser.add_argument("--repo", required=True, help="owner/name")
    args = parser.parse_args(argv)
    report = json.loads(read_text(args.report))
    for line in sync(report, args.repo, run_gh):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
