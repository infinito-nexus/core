"""Lint: every ``upstream:`` directive names one issue or pull request.

The directive ties a workaround to the upstream item whose resolution makes it
removable, and ``tests/external/repository/test_upstream_references.py`` asks
that item's tracker whether it is still open. It can only ask a tracker it
knows, so this lint holds every directive in the tracked and untracked files to
the shapes ``utils.upstream.directive.classify`` accepts: a GitHub issue or
pull request, a GitLab issue or merge request (subgroups allowed, any host), or
a Forgejo/Gitea issue or pull request (codeberg.org, gitea.com, any
self-hosted host). One URL per directive, nothing after it.

The negative control feeds the same check a directive of every rejected shape,
in every comment syntax, so a scan that silently stopped finding directives or
a classifier that started accepting anything turns this lint red instead of
leaving it green. The guide is ``docs/contributing/actions/testing/upstream.md``.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.upstream.directive import classify, directives_in, repository_directives

if TYPE_CHECKING:
    from collections.abc import Iterable

    from utils.upstream.directive import Directive

GITHUB = "github.com"
GITLAB = "gitlab.com"
CODEBERG = "codeberg.org"

ACCEPTED = (
    f"https://{GITHUB}/owner/repo/issues/1",
    f"https://{GITHUB}/owner/repo/pull/2#issuecomment-3",
    f"https://{GITLAB}/group/sub/project/-/issues/4",
    f"https://{GITLAB}/group/project/-/merge_requests/5",
    f"https://{CODEBERG}/owner/repo/pulls/6",
)
REJECTED = (
    "see the upstream tracker",
    f"https://{GITHUB}/owner/repo/issues/1 and more",
    f"https://{GITHUB}/owner/repo/issues/1 https://{GITHUB}/owner/repo/issues/2",
    f"http://{GITHUB}/owner/repo/issues/1",
    f"https://{GITHUB}/owner/repo/pulls/1",
    f"https://{GITHUB}/owner/repo/issues",
    f"https://{GITHUB}/owner/repo/issues/1?page=2",
    f"https://{GITHUB}/owner/repo/pull/1/files",
    f"https://{GITLAB}/group/project/issues/1",
    f"https://{GITLAB}/project/-/issues/1",
    f"https://{CODEBERG}/owner/repo/pull/1",
    f"https://{CODEBERG}:8443/owner/repo/issues/1",
    "https://bugs.launchpad.invalid/ubuntu/+bug/1",
)
PREFIXES = (("#", ""), ("//", ""), ("/*", " */"), ("{#", " #}"), ("<!--", " -->"))


def offenders(directives: Iterable[Directive]) -> list[str]:
    """``path:line: text`` for every directive whose text names no tracker item.

    Args:
        directives: the directives to check.
    """
    return [
        f"{d.path}:{d.line}: {d.text!r}" for d in directives if classify(d.text) is None
    ]


def _commented(text: str) -> list[str]:
    """One line per comment syntax, each carrying *text* as a directive.

    Args:
        text: what follows the keyword.
    """
    return [f"{opener} upstream: {text}{closer}" for opener, closer in PREFIXES]


class TestUpstreamDirectives(unittest.TestCase):
    def test_every_directive_names_one_tracker_item(self) -> None:
        found = offenders(repository_directives())
        self.assertEqual(
            found,
            [],
            "These upstream: directives do not name exactly one GitHub issue or"
            " pull request, GitLab issue or merge request, or Forgejo/Gitea issue"
            " or pull request, so the external check cannot ask their tracker."
            " Write one URL per directive, nothing after it; see"
            " docs/contributing/actions/testing/upstream.md:\n" + "\n".join(found),
        )

    def test_negative_control_rejects_every_wrong_shape(self) -> None:
        for text in REJECTED:
            lines = _commented(text)
            with self.subTest(text=text):
                found = offenders(directives_in("control.txt", lines))
                self.assertEqual(len(found), len(lines), found)

    def test_negative_control_accepts_every_tracker_shape(self) -> None:
        for text in ACCEPTED:
            lines = _commented(text)
            with self.subTest(text=text):
                directives = directives_in("control.txt", lines)
                self.assertEqual(len(directives), len(lines))
                self.assertEqual(offenders(directives), [])


if __name__ == "__main__":
    unittest.main()
