"""Model references the assistant accepts: each pinned to one explicit version.

A reference is ``<name>:<tag>`` or ``<name>@sha256:<digest>``. A bare name and
the ``latest`` tag let the model service fetch whatever it resolves at pull
time, so the role config refuses both, and the service refuses to start on
one, which keeps a deploy from pulling an unpinned model.
"""

from __future__ import annotations

import re

_NAME = r"[a-z0-9][a-z0-9._/-]*"
_PINNED = re.compile(
    rf"^{_NAME}(?::(?P<tag>[A-Za-z0-9][A-Za-z0-9._-]*)|@sha256:[0-9a-f]{{64}})$"
)
FLOATING_TAGS = frozenset({"latest", "main", "master", "stable"})


def pinned(reference: str) -> bool:
    """Return whether *reference* names exactly one model version.

    Args:
        reference: a model reference as the role config spells it.
    """
    match = _PINNED.match(str(reference).strip())
    if not match:
        return False
    tag = match.group("tag")
    return tag is None or tag.lower() not in FLOATING_TAGS


def unpinned(models: dict) -> list[str]:
    """Return the keys of *models* whose reference is not pinned.

    Args:
        models: model role (``end_user``, ``consultant``, ``embedding``) to reference.
    """
    return sorted(key for key, reference in models.items() if not pinned(reference))
