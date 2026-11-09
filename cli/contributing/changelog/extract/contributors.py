"""Contributors of a release range, their commit counts and GitHub profiles.

Authors come from ``git shortlog -sne`` and co-authors from the
``Co-authored-by`` trailers, both under the repository's ``.mailmap``; bots and
coding assistants are dropped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cli.contributing.changelog.extract import git
from utils.cache.files import read_text

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PROFILE = "https://github.com/{login}"
_SHORTLOG = re.compile(r"^\s*(\d+)\t(.+?) <([^>]*)>\s*$")
_CONTACT = re.compile(r"^\s*(.+?)\s*<([^>]+)>\s*$")
_NOREPLY = re.compile(
    r"^(?:\d+\+)?([A-Za-z0-9-]+)@users\.noreply\.github\.com$", re.IGNORECASE
)
_BOT = re.compile(
    r"\[bot\]|dependabot|renovate|github-actions|copilot"
    r"|^noreply@(?:anthropic\.com|openai\.com)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Contributor:
    """One person of the range.

    Args:
        name: The canonical name.
        email: The canonical email.
        commits: Authored commits plus co-authored ones.
        profile: The GitHub profile URL, ``None`` when no login is known.
    """

    name: str
    email: str
    commits: int
    profile: str | None


def is_bot(name: str, email: str) -> bool:
    """Tell whether an identity is a bot or a coding assistant.

    Args:
        name: The identity's name.
        email: The identity's email.
    """
    return bool(_BOT.search(name) or _BOT.search(email))


def parse_shortlog(output: str) -> dict[tuple[str, str], int]:
    """Parse ``git shortlog -sne`` output.

    Args:
        output: The command's output.

    Returns:
        ``{(name, email): commits}``.
    """
    counts = {}
    for line in output.splitlines():
        if match := _SHORTLOG.match(line):
            counts[(match.group(2), match.group(3))] = int(match.group(1))
    return counts


def parse_contacts(output: str) -> list[tuple[str, str]]:
    """Parse ``Name <email>`` lines, one per trailer value.

    Args:
        output: Trailer values or ``git check-mailmap`` output.
    """
    return [
        (match.group(1), match.group(2))
        for line in output.splitlines()
        if (match := _CONTACT.match(line))
    ]


def login_of(email: str, logins: dict[str, str]) -> str | None:
    """Return the GitHub login of an email from its noreply form or the cache.

    Args:
        email: The canonical email.
        logins: The cached ``{email: login}`` mapping.
    """
    noreply = _NOREPLY.match(email)
    return noreply.group(1) if noreply else logins.get(email.lower())


def tally(
    authors: dict[tuple[str, str], int],
    co_authors: list[tuple[str, str]],
    logins: dict[str, str],
) -> list[Contributor]:
    """Merge authors and co-authors into the contributor list.

    Args:
        authors: ``parse_shortlog`` output, canonical identities.
        co_authors: One canonical ``(name, email)`` per co-author trailer.
        logins: The cached ``{email: login}`` mapping.

    Returns:
        The contributors without bots, most commits first, then by name.
    """
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for (name, email), commits in authors.items():
        key = email.lower()
        counts[key] = counts.get(key, 0) + commits
        names.setdefault(key, name)
    for name, email in co_authors:
        key = email.lower()
        counts[key] = counts.get(key, 0) + 1
        names.setdefault(key, name)
    people = []
    for key, commits in counts.items():
        if is_bot(names[key], key):
            continue
        login = login_of(key, logins)
        profile = PROFILE.format(login=login) if login else None
        people.append(Contributor(names[key], key, commits, profile))
    return sorted(people, key=lambda person: (-person.commits, person.name))


def read_logins(path: Path | None) -> dict[str, str]:
    """Return the cached ``{email: login}`` mapping, empty when absent.

    Args:
        path: The JSON cache file, or ``None``.
    """
    if path is None or not path.is_file():
        return {}
    return {
        key.lower(): value for key, value in json.loads(read_text(str(path))).items()
    }


def resolve_logins(
    repo: Path,
    base: str,
    head: str,
    logins: dict[str, str],
    lookup: Callable[[str], str | None],
) -> dict[str, str]:
    """Add the login of every author the cache misses, one commit each.

    Args:
        repo: The repository.
        base: The base ref.
        head: The target ref.
        logins: The cached ``{email: login}`` mapping; it is not changed.
        lookup: Maps a commit SHA to its author's GitHub login, ``None`` when
            GitHub knows none.

    Returns:
        The cache with every resolved login added.
    """
    found = dict(logins)
    output = git.run(repo, "log", "--format=%H%x09%aE", f"{base}..{head}")
    for line in output.splitlines():
        sha, _, email = line.partition("\t")
        key = email.lower()
        if key in found or login_of(key, found) or is_bot("", key):
            continue
        if login := lookup(sha):
            found[key] = login
    return found


def collect(
    repo: Path, base: str, head: str, logins: dict[str, str]
) -> list[Contributor]:
    """Return the contributors of ``base..head``.

    Args:
        repo: The repository; its ``.mailmap`` maps every identity.
        base: The base ref.
        head: The target ref.
        logins: The ``{email: login}`` mapping for the profile URLs.
    """
    span = f"{base}..{head}"
    authors = parse_shortlog(git.run(repo, "shortlog", "-sne", span))
    trailers = git.run(
        repo, "log", "--format=%(trailers:key=Co-authored-by,valueonly)", span
    )
    raw = sorted({f"{name} <{email}>" for name, email in parse_contacts(trailers)})
    co_authors = parse_contacts(git.run(repo, "check-mailmap", *raw)) if raw else []
    canonical = dict(zip(raw, co_authors, strict=True))
    per_trailer = [
        canonical[f"{name} <{email}>"] for name, email in parse_contacts(trailers)
    ]
    return tally(authors, per_trailer, logins)


def section(people: list[Contributor]) -> str:
    """Return the ``Contributors`` block of a changelog entry.

    Args:
        people: The contributors, as ``collect`` returns them.
    """
    rows = [
        f"- [{person.name}]({person.profile})" if person.profile else f"- {person.name}"
        for person in people
    ]
    return "Contributors:\n\n" + "\n".join(rows) + "\n"
