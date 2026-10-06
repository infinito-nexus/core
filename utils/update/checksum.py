"""Move a pin's companion checksum together with its version.

A version pin whose asset is fetched by digest carries a second pin: the
digest itself. Bumping only the version leaves the digest describing the
previous release, and the next build dies on a ``digest mismatch`` that names
neither the pin nor the role. Such a pin declares both keys::

    docs:
      mermaid_version: 12.1.0
      mermaid_sha256: 6484afc3...
      update:
        - key: mermaid_version
          type: npm
          package: mermaid
          checksum_key: mermaid_sha256
          checksum_url: "https://cdn.jsdelivr.net/npm/mermaid@{version}/dist/mermaid.min.js"

``checksum_url`` carries ``{version}``, which resolves to the version being
written, and the SHA-256 of what it serves replaces ``checksum_key``.
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from typing import Any

from utils.update.pins import key_line, top_level_line

CHECKSUM_KEY = "checksum_key"
CHECKSUM_URL = "checksum_url"
PLACEHOLDER = "{version}"
TIMEOUT_SECONDS = 60
USER_AGENT = "infinito-nexus-version-source"
_VALUE_RE = re.compile(r"(:[ \t]*)\S+")


def digest(url: str) -> str:
    """Return the SHA-256 hex digest of the asset *url* serves.

    Args:
        url: asset the checksum pin covers.
    """
    request = urllib.request.Request(  # noqa: S310 - https URL of a declared version source
        url, headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(  # noqa: S310 - https URL of a declared version source
        request, timeout=TIMEOUT_SECONDS
    ) as response:
        return hashlib.sha256(response.read()).hexdigest()


def problems(label: str, key: str, config: dict[str, Any], source: Any) -> list[str]:
    """Return what keeps a declared companion checksum from being rewritten.

    Args:
        label: ``<role>/<entity>`` as it appears in the message.
        key: the version key the checksum belongs to.
        config: mapping that carries both pins.
        source: the ``update:`` block.
    """
    declared = source.get(CHECKSUM_KEY)
    if declared is None:
        return []
    found: list[str] = []
    if str(declared) not in config:
        found.append(
            f"{label}.{key}: update.{CHECKSUM_KEY} '{declared}' names no key "
            "beside the version pin"
        )
    if PLACEHOLDER not in str(source.get(CHECKSUM_URL, "")):
        found.append(
            f"{label}.{key}: update.{CHECKSUM_URL} must carry '{PLACEHOLDER}' "
            "so the bumped version reaches the asset"
        )
    return found


def rewrite(lines: list[str], entity: str, source: Any, version: str) -> None:
    """Replace the declared checksum in *lines* with the one *version* serves.

    Args:
        lines: lines of the file that carries both pins, modified in place.
        entity: top-level key whose block holds the pins, empty for an addon.
        source: the ``update:`` block.
        version: version being written.
    """
    declared = str(source.get(CHECKSUM_KEY, ""))
    if not declared:
        return
    url = str(source[CHECKSUM_URL]).replace(PLACEHOLDER, version)
    number = (
        key_line(lines, entity, declared) if entity else top_level_line(lines, declared)
    )
    if number is None:
        return
    index = number - 1
    lines[index] = _VALUE_RE.sub(rf"\g<1>{digest(url)}", lines[index], count=1)
