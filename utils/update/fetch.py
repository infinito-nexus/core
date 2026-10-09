"""Read the documents a declared version source names.

Every document is fetched once per run, so the pins that read the same release
manifest resolve against one snapshot of it.
"""

from __future__ import annotations

import functools
import urllib.request

TIMEOUT_SECONDS = 30
USER_AGENT = "infinito-nexus-version-source"


def get(url: str, headers: dict[str, str] | None = None) -> bytes:
    """Return the body of a declared version source.

    Args:
        url: https URL to read.
        headers: request headers beside the user agent.
    """
    request = urllib.request.Request(  # noqa: S310 - https URL of a declared version source
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    with urllib.request.urlopen(  # noqa: S310 - https URL of a declared version source
        request, timeout=TIMEOUT_SECONDS
    ) as response:
        return response.read()


@functools.cache
def document(url: str) -> str:
    """Return the text of *url*, fetched once per run."""
    return get(url).decode("utf-8", "replace")


def documents(urls: str | list[str]) -> str:
    """Return the text of one URL, or of several as one text.

    Args:
        urls: a URL, or several whose bodies are searched together.
    """
    return "\n".join(
        document(url) for url in ([urls] if isinstance(urls, str) else urls)
    )
