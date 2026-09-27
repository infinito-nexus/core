"""Render the declared repositories as the records Nexus is bootstrapped from.

One format, two readers: the ``.env`` generator writes it to
``INFINITO_CACHE_UPSTREAMS`` for the dev stack, and the ``cache_records``
lookup hands the same string to the role's bootstrap task. Both resolve the
Ubuntu mirror placeholders from ``INFINITO_APT_UBUNTU_MIRRORS``, which the
image build reads too, so the mirror order has a single home.

Stdlib only: the ``.env`` generator reaches this before PyYAML exists.
"""

from __future__ import annotations

import os

from utils.cache.hosts import declarations

MIRRORS_KEY = "INFINITO_APT_UBUNTU_MIRRORS"
PRIMARY = "${UBUNTU_PRIMARY}"
FALLBACK = "${UBUNTU_FALLBACK}"
PLACEHOLDER = "${"
FIELD = "|"
RECORD = ","


def mirrors(raw: str = "") -> tuple[str, str] | None:
    """Return the primary and fallback Ubuntu archive, without trailing slash.

    Args:
        raw: the mirror list, or empty to read it from the environment.

    Returns:
        None where the list does not carry both, in which case the
        placeholders cannot be resolved.
    """
    found = [
        entry.rstrip("/")
        for entry in (raw or os.environ.get(MIRRORS_KEY, "")).strip('"').split()
        if entry
    ]
    if len(found) < 2:
        return None
    return found[0], found[1]


def upstream(raw: str, resolved: tuple[str, str] | None) -> str:
    """Return *raw* with the Ubuntu mirror placeholders substituted."""
    if resolved is None:
        return raw
    return raw.replace(PRIMARY, resolved[0]).replace(FALLBACK, resolved[1])


def records(raw_mirrors: str = "") -> str:
    """Return every repository as ``name|flavor|url|suite|depth|max_age``.

    Args:
        raw_mirrors: the mirror list, or empty to read it from the environment.

    Returns:
        The comma-separated records, or the empty string where a placeholder
        stays unresolved, so a consumer's own guard reports it rather than
        Nexus proxying a host that does not exist.
    """
    resolved = mirrors(raw_mirrors)
    rendered = []
    for repo in declarations().repos:
        url = upstream(repo.upstream, resolved)
        if PLACEHOLDER in url:
            return ""
        rendered.append(
            FIELD.join(
                (
                    repo.name,
                    repo.flavor,
                    url,
                    repo.distribution,
                    str(repo.repodata_depth or ""),
                    repo.content_max_age,
                )
            )
        )
    return RECORD.join(rendered)
