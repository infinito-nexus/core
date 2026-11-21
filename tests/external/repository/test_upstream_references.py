"""Every upstream issue or pull request a workaround waits on is still open.

An ``upstream:`` directive sits on or directly above a patch or workaround and
names the upstream item whose resolution makes it removable; the guide is
``docs/contributing/actions/testing/upstream.md``. This suite collects every
directive in the files ``git ls-files`` lists, asks each item's tracker once
and fails as soon as an item is closed in any way: a pull or merge request
merged or closed unmerged, an issue closed as completed, as not planned or as a
duplicate. A directive whose tracker answers 404 or 410 fails too, because it
waits on nothing.

This is an external test because it performs live requests against the GitHub,
GitLab and Forgejo/Gitea REST APIs the directives name. Requests share the
per-host gate of the other probe suites in this package.

A tracker that could not be asked never turns into a pass. A timeout, a
connection error, HTTP 429 and 5xx are retried first. An item still unanswered
after that, or behind an auth wall, fails the run, the way an unverified
package fails ``test_packages_available.py``: a green run would claim a
verification that did not happen.

An exhausted rate limit skips its items instead. GitHub answers 60
unauthenticated requests per hour and address, and every session on a shared
host spends the same budget, so a failure there would turn every local gate red
with no upstream change behind it. The skip reason names each URL, the
directive's ``file:line`` and when the limit resets; ``GITHUB_TOKEN`` or
``GH_TOKEN`` avoids it. A run with a failing item still fails and lists the
skipped ones.
"""

from __future__ import annotations

import concurrent.futures
import unittest
from collections import defaultdict
from typing import TYPE_CHECKING

from utils.annotations.message import error, warning
from utils.update.base import resolve_max_fetch_workers
from utils.upstream.directive import classify, repository_directives
from utils.upstream.trackers import (
    CLOSED,
    MISSING,
    OPEN,
    RATE_LIMITED,
    api_url,
    status_of,
)

from ._host_gate import host_gate

if TYPE_CHECKING:
    from utils.upstream.directive import Directive, Reference
    from utils.upstream.trackers import Status

_PER_HOST_REQUESTS = 2

REMOVAL = "Check that the pinned version contains the fix before removing the patch."
CLOSED_HEADLINE = (
    f"upstream item(s) are closed. {REMOVAL} If the workaround is still needed,"
    " reference the open item that tracks the defect now."
)
MISSING_HEADLINE = (
    "directive(s) name an item the tracker does not serve: fix the URL, or"
    " reference the item that tracks the defect now."
)
UNVERIFIED_HEADLINE = (
    "upstream item(s) could not be checked, so a green run would claim a"
    " verification that did not happen. A network error needs a host with a"
    " route to the tracker; an auth wall needs GITHUB_TOKEN or GH_TOKEN (GitHub)"
    " or GITLAB_TOKEN (gitlab.com)."
)
RATE_LIMITED_HEADLINE = (
    "upstream item(s) skipped behind an exhausted rate limit. GITHUB_TOKEN or"
    " GH_TOKEN avoids it on GitHub, GITLAB_TOKEN on gitlab.com."
)


def _references() -> dict[Reference, list[Directive]]:
    """Every tracker item a directive names, with the directives naming it."""
    found: dict[Reference, list[Directive]] = defaultdict(list)
    for directive in repository_directives():
        reference = classify(directive.text)
        if reference is not None:
            found[reference].append(directive)
    return dict(found)


def _ask(reference: Reference) -> Status:
    """Ask one item's tracker, holding the per-host gate for every attempt.

    Args:
        reference: the item a directive names.
    """
    with host_gate(api_url(reference), _PER_HOST_REQUESTS):
        return status_of(reference)


def _finding(directive: Directive, status: Status) -> str:
    """``path:line: <url> is <state> on <date>`` for one directive.

    Args:
        directive: the directive naming the item.
        status: what the tracker said about the item.
    """
    date = f" on {status.date}" if status.date else ""
    return (
        f"{directive.path}:{directive.line}: {directive.text} is {status.state}{date}"
    )


def _skipped(directive: Directive, status: Status) -> str:
    """``path:line: <url> is rate limited, the limit resets <when>`` for one directive.

    Args:
        directive: the directive naming the item.
        status: the rate-limited answer; its ``date`` says when the limit resets.
    """
    return (
        f"{directive.path}:{directive.line}: {directive.text} is {status.state},"
        f" the limit resets {status.date}"
    )


class TestUpstreamReferences(unittest.TestCase):
    def test_every_referenced_item_is_still_open(self) -> None:
        references = _references()
        if not references:
            self.skipTest("no upstream: directive names a tracker item")

        ordered = sorted(references)
        workers = min(resolve_max_fetch_workers(), len(ordered))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            statuses = dict(zip(ordered, pool.map(_ask, ordered), strict=True))

        findings = [
            (directive, statuses[reference])
            for reference in ordered
            for directive in references[reference]
        ]
        closed = [f for f in findings if f[1].verdict == CLOSED]
        missing = [f for f in findings if f[1].verdict == MISSING]
        limited = [f for f in findings if f[1].verdict == RATE_LIMITED]
        unverified = [
            f
            for f in findings
            if f[1].verdict not in (OPEN, CLOSED, MISSING, RATE_LIMITED)
        ]

        for directive, status in limited:
            warning(
                _skipped(directive, status),
                title="Upstream rate limited",
                file=directive.path,
                line=directive.line,
            )
        skipped = (
            f"{len(limited)} {RATE_LIMITED_HEADLINE}\n"
            + "\n".join(f"  {_skipped(d, s)}" for d, s in limited)
            if limited
            else ""
        )

        report: list[str] = []
        for found, title, headline, hint in (
            (closed, "Upstream closed", CLOSED_HEADLINE, f" {REMOVAL}"),
            (missing, "Upstream missing", MISSING_HEADLINE, ""),
            (unverified, "Upstream unverified", UNVERIFIED_HEADLINE, ""),
        ):
            if not found:
                continue
            for directive, status in found:
                error(
                    _finding(directive, status) + hint,
                    title=title,
                    file=directive.path,
                    line=directive.line,
                )
            report.append(
                f"{len(found)} {headline}\n"
                + "\n".join(f"  {_finding(d, s)}" for d, s in found)
            )
        if report:
            self.fail("\n\n".join([*report, skipped] if skipped else report))
        if skipped:
            self.skipTest(skipped)


if __name__ == "__main__":
    unittest.main()
