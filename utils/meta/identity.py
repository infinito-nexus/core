"""Who an author is, and where their public profile lives.

``.mailmap`` maps every address a person has committed under to their
``@infinito.nexus`` address, and that address names their profile: the local
part is the profile slug. One social profile is therefore the single point of
truth for an author, and nothing here keeps a second copy of their name, URL
or avatar.
"""

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

DOMAIN = "infinito.nexus"
PROFILE_BASE = f"https://social.{DOMAIN}/profile"
MAILMAP = ".mailmap"

_CANONICAL = re.compile(r"^(?P<name>[^<#]+?)\s*<(?P<email>[^>]+)>")
_ENTRY = re.compile(
    r"^(?P<name>[^<#]+?)?\s*<(?P<email>[^>]+)>"
    r"(?:\s*(?P<alias_name>[^<#]+?)?\s*<(?P<alias_email>[^>]+)>)?\s*$"
)


def profile_url(email: str) -> str:
    """Return the public profile the address names, empty for a foreign one.

    Args:
        email: an author's address.
    """
    local, _, domain = email.strip().partition("@")
    if domain.lower() != DOMAIN or not local:
        return ""
    return f"{PROFILE_BASE}/{local}/profile"


@lru_cache(maxsize=1)
def _aliases(root: str = str(PROJECT_ROOT)) -> dict[str, tuple[str, str]]:
    """Return ``{commit address: canonical (name, address)}``.

    Exception: ``.mailmap`` is parsed here rather than handed to
    ``git check-mailmap``, because the test container mounts the checkout
    without the worktree's git directory and git then refuses to read it.

    Args:
        root: repository root, as a string so the cache key stays hashable.
    """
    path = Path(root, MAILMAP)
    if not path.is_file():
        return {}
    found: dict[str, tuple[str, str]] = {}
    for line in read_text(str(path)).splitlines():
        match = _ENTRY.match(line.strip())
        if not match:
            continue
        name = (match.group("name") or "").strip()
        email = match.group("email")
        alias = match.group("alias_email") or email
        found[alias.lower()] = (name, email)
    return found


def canonical(name: str, email: str, root: Path | None = None) -> tuple[str, str]:
    """Return the identity ``.mailmap`` folds ``name``/``email`` into.

    Args:
        name: the name the commit carries.
        email: the address the commit carries.
        root: repository root; defaults to this checkout.

    Returns:
        ``(name, email)``, unchanged when the mailmap knows the address not.
    """
    mapped = _aliases(str(root or PROJECT_ROOT)).get(email.strip().lower())
    if not mapped:
        return name, email
    return mapped[0] or name, mapped[1]


@lru_cache(maxsize=1)
def by_name(root: str = str(PROJECT_ROOT)) -> dict[str, str]:
    """Return ``{author name: canonical address}`` as ``.mailmap`` declares it.

    Args:
        root: repository root, as a string so the cache key stays hashable.
    """
    path = Path(root, MAILMAP)
    if not path.is_file():
        return {}
    found: dict[str, str] = {}
    for line in read_text(str(path)).splitlines():
        match = _CANONICAL.match(line.strip())
        if match:
            found[match.group("name")] = match.group("email")
    return found


def committing_as(root: Path | None = None) -> tuple[str, str]:
    """Return the identity a commit made here right now would carry.

    Exception: the env pair wins over git. The test container mounts the
    checkout but not the contributor's git configuration, so asking git there
    yields nothing; ``utils/env/handlers/infinito/git_identity.py`` records the
    host's answer in the ``.env`` the container reads.

    Args:
        root: repository root; defaults to this checkout.

    Returns:
        ``(name, email)``; either is empty when neither source knows it.
    """
    carried = (
        os.environ.get("INFINITO_GIT_AUTHOR_NAME", "").strip(),
        os.environ.get("INFINITO_GIT_AUTHOR_EMAIL", "").strip(),
    )
    if carried[1]:
        return carried
    base = ["git", "-C", str(root or PROJECT_ROOT), "config", "--get"]
    values = [
        subprocess.run([*base, key], capture_output=True, text=True, check=False)
        for key in ("user.name", "user.email")
    ]
    return tuple(value.stdout.strip() for value in values)  # type: ignore[return-value]
