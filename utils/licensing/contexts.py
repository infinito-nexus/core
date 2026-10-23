"""In which context a role's deployed software may be used.

The project licence governs this repository's own code. It does not reach the
software a role deploys, and that software is where the restriction usually
sits: a deployment holding written permission for commercial use of
Infinito.Nexus is still barred from NLLB-200's weights, which are CC BY-NC.

A boolean would be wrong for most of the catalogue, because the common answer
is neither yes nor no but "yes, and offering it as a service obliges you to
publish your changes". The classes below keep that distinction.

``unknown`` is a legitimate value and the default for anything unread. A gap
has to be visible; a role silently absent from the index would read as safe.
"""

from __future__ import annotations

from typing import NamedTuple


class Context(NamedTuple):
    """One licence class and what it permits.

    Args:
        key: the value written in ``meta/info.yml``.
        title: heading for the generated page.
        commercial: short verdict on commercial use.
        duties: what the deployer owes beyond using it.
    """

    key: str
    title: str
    commercial: str
    duties: str


PERMISSIVE = Context(
    "permissive",
    "Permissive",
    "allowed",
    "keep the copyright notice and the licence text",
)
COPYLEFT = Context(
    "copyleft",
    "Copyleft",
    "allowed",
    "publish the source of changes you distribute",
)
COPYLEFT_NETWORK = Context(
    "copyleft-network",
    "Network copyleft",
    "allowed",
    "publish the source of changes once you offer it over a network, "
    "which a hosted deployment does",
)
SOURCE_AVAILABLE = Context(
    "source-available",
    "Source available, not open source",
    "restricted by the vendor's terms",
    "read the licence before offering it as a service; several forbid exactly that",
)
NON_COMMERCIAL = Context(
    "non-commercial",
    "Non-commercial only",
    "prohibited",
    "use privately or for education; a commercial deployment needs a separate grant",
)
PROPRIETARY = Context(
    "proprietary",
    "Proprietary",
    "decided by the vendor's agreement",
    "accept the vendor's terms; redistribution is usually forbidden",
)
UNKNOWN = Context(
    "unknown",
    "Not yet determined",
    "unknown, assume the strictest",
    "establish the licence before relying on this role commercially",
)

CONTEXTS: tuple[Context, ...] = (
    PERMISSIVE,
    COPYLEFT,
    COPYLEFT_NETWORK,
    SOURCE_AVAILABLE,
    NON_COMMERCIAL,
    PROPRIETARY,
    UNKNOWN,
)

BY_KEY: dict[str, Context] = {context.key: context for context in CONTEXTS}

ORDER: tuple[str, ...] = tuple(context.key for context in CONTEXTS)
