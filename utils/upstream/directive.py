"""The ``upstream:`` directive ties a workaround to the upstream issue or pull
request whose resolution makes the workaround removable.

Grammar, one URL per directive::

    <prefix> upstream: <url> <closer>

``<prefix>`` is one of ``#``, ``//``, ``/*``, ``{#`` and ``<!--``. It opens the
line or follows whitespace, so a prefix quoted at the start of a string literal
or inside a markdown code span is not a directive. ``<closer>`` is the ``*/``,
``#}`` or ``-->`` the prefix needs; nothing else may follow the URL. A
``.patch`` or ``.diff`` file also takes the bare form ``upstream: <url>`` as a
header line above its first diff header, where ``git apply`` reads no text.

``<url>`` names one issue or pull request:

* GitHub: ``https://github.com/<owner>/<repo>/(issues|pull)/<n>``
* GitLab, on gitlab.com or a self-hosted instance, subgroups allowed:
  ``https://<host>/<group>[/<subgroup>...]/<project>/-/(issues|merge_requests)/<n>``
* Forgejo or Gitea, on codeberg.org, gitea.com or a self-hosted instance:
  ``https://<host>/<owner>/<repo>/(issues|pulls)/<n>``

A ``#fragment`` such as ``#issuecomment-1`` may follow the number. A query, a
port, credentials or a deeper path may not. The contributor guide is
``docs/contributing/actions/testing/upstream.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import urlsplit

from utils.cache.files import PROJECT_ROOT, repository_files

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

KEYWORD = "upstream:"
_KEYWORD_BYTES = KEYWORD.encode()
_SKIPPED_TREES = ("locale/",)
_BINARY_PROBE_BYTES = 4096

GITHUB = "github"
GITLAB = "gitlab"
GITEA = "gitea"

ISSUE = "issue"
PULL = "pull"

_GITHUB_HOST = "github.com"
_GITLAB_HOST = "gitlab.com"

_COMMENTED = re.compile(
    r"(?:^|(?<=\s))(?:#|//|/\*|\{#|<!--)[ \t]*upstream:(?P<rest>.*)$"
)
_BARE = re.compile(r"^upstream:(?P<rest>.*)$")
_PATCH_SUFFIXES = (".patch", ".diff")
_PATCH_BODY = re.compile(r"^(?:diff |--- |---$|Index: |@@ )")
_CLOSERS = ("-->", "#}", "*/")

_SEGMENT = r"[A-Za-z0-9_.][A-Za-z0-9_.-]*"
_NUMBER = r"(?P<number>[1-9][0-9]*)"
_SHAPES = (
    (
        GITHUB,
        re.compile(
            rf"/(?P<project>{_SEGMENT}/{_SEGMENT})/(?P<kind>issues|pull)/{_NUMBER}"
        ),
    ),
    (
        GITLAB,
        re.compile(
            rf"/(?P<project>{_SEGMENT}(?:/{_SEGMENT})+)"
            rf"/-/(?P<kind>issues|merge_requests)/{_NUMBER}"
        ),
    ),
    (
        GITEA,
        re.compile(
            rf"/(?P<project>{_SEGMENT}/{_SEGMENT})/(?P<kind>issues|pulls)/{_NUMBER}"
        ),
    ),
)


@dataclass(frozen=True, order=True)
class Reference:
    """One issue or pull request on a tracker.

    Attributes:
        forge: ``github``, ``gitlab`` or ``gitea``; Forgejo answers the Gitea API.
        host: the tracker's hostname.
        project: ``<owner>/<repo>``, or the full group path of a GitLab project.
        kind: ``issue`` or ``pull``; a GitLab merge request is a ``pull``.
        number: the item's number within its project.
    """

    forge: str
    host: str
    project: str
    kind: str
    number: int


class Directive(NamedTuple):
    """One ``upstream:`` directive as written.

    Attributes:
        path: repository-relative POSIX path of the file that carries it.
        line: 1-based line number.
        text: everything after ``upstream:``, with the comment closer removed.
    """

    path: str
    line: int
    text: str


def opens_directive(body: str) -> bool:
    """Whether a comment body, its prefix already stripped, is a directive.

    Args:
        body: the comment text without its ``#``, ``//``, ``/*``, ``{#`` or
            ``<!--`` prefix and without surrounding whitespace.
    """
    return body.startswith(KEYWORD)


def _hosts(forge: str, host: str) -> bool:
    """Whether a URL shape of *forge* can live on *host*.

    Args:
        forge: one of ``github``, ``gitlab`` and ``gitea``.
        host: the URL's lowercased hostname.
    """
    if forge == GITHUB:
        return host == _GITHUB_HOST
    if forge == GITLAB:
        return host != _GITHUB_HOST
    return host not in (_GITHUB_HOST, _GITLAB_HOST)


def classify(text: str) -> Reference | None:
    """Read a directive's text as one tracker item.

    Args:
        text: what follows ``upstream:``, with the comment closer removed.

    Returns:
        The referenced item, or ``None`` when *text* is not exactly one
        accepted issue or pull request URL.
    """
    if not text or "?" in text or any(char.isspace() for char in text):
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = parts.hostname or ""
    if parts.scheme != "https" or not host or parts.netloc.lower() != host:
        return None
    for forge, shape in _SHAPES:
        if not _hosts(forge, host):
            continue
        match = shape.fullmatch(parts.path)
        if match:
            kind = ISSUE if match["kind"] == "issues" else PULL
            return Reference(forge, host, match["project"], kind, int(match["number"]))
    return None


def _without_closer(rest: str) -> str:
    """Strip the comment closer and surrounding whitespace from a directive.

    Args:
        rest: the raw text after ``upstream:``.
    """
    text = rest.strip()
    for closer in _CLOSERS:
        if text.endswith(closer):
            return text[: -len(closer)].rstrip()
    return text


def directives_in(path: str, lines: Sequence[str]) -> list[Directive]:
    """Every ``upstream:`` directive in one file.

    Args:
        path: repository-relative POSIX path; a ``.patch`` or ``.diff`` suffix
            also admits the bare header form above the first diff header.
        lines: the file's lines.
    """
    header = path.endswith(_PATCH_SUFFIXES)
    found: list[Directive] = []
    for number, line in enumerate(lines, start=1):
        if header and _PATCH_BODY.match(line):
            header = False
        match = _COMMENTED.search(line) or (_BARE.match(line) if header else None)
        if match:
            found.append(Directive(path, number, _without_closer(match["rest"])))
    return found


def _candidate_text(path: Path) -> str | None:
    """The text of a file that may carry a directive, read without a cache.

    Args:
        path: absolute path of a listed file.

    Returns:
        ``None`` for a file that cannot be opened, a binary file (a NUL byte
        in its first bytes) and a file without the keyword.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(_BINARY_PROBE_BYTES)
            if b"\0" in head:
                return None
            data = head + handle.read()
    except OSError:
        return None
    if _KEYWORD_BYTES not in data:
        return None
    return data.decode("utf-8", errors="replace")


def repository_directives() -> list[Directive]:
    """Every ``upstream:`` directive in the files ``git ls-files`` lists.

    Tracked and untracked-not-ignored files count. ``locale/`` is skipped: its
    generated catalogs hold no workaround and are most of the tree's bytes.
    """
    found: list[Directive] = []
    for rel in repository_files(untracked=True):
        if rel.startswith(_SKIPPED_TREES):
            continue
        text = _candidate_text(PROJECT_ROOT / rel)
        if text is not None:
            found.extend(directives_in(rel, text.splitlines()))
    return found
