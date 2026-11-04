"""Validation of the per-user ``forward`` key in the merged users catalogue."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def validate_forwards(users: Mapping[str, Any]) -> None:
    """Refuse a ``forward`` that names no user.

    Args:
        users: users keyed by canonical key, before rendering; ``forward``
            names the key of the user that receives the mail sent to this
            user, '' for none. A forward that is still a Jinja expression is
            left to the consumer, which sees it rendered.

    Raises:
        TypeError: a forward that is no string, or a forward to a user whose
            entry is no mapping, as ``_load_user_defs`` raises for one.
        ValueError: a forward to an unknown user, or a chain of forwards that
            returns to a user it already passed.
    """
    for key, user in users.items():
        if not isinstance(user, Mapping):
            continue
        chain = [key]
        target = user["forward"]
        while target:
            if not isinstance(target, str):
                raise TypeError(
                    f"User '{chain[-1]}' declares forward={target!r}; a user key is required"
                )
            if "{{" in target or "{%" in target:
                break
            if target in chain:
                raise ValueError(
                    f"Forward loop: {' -> '.join([*chain, target])} in merged users"
                )
            if target not in users:
                raise ValueError(
                    f"User '{chain[-1]}' forwards to unknown user '{target}'"
                )
            receiver = users[target]
            if not isinstance(receiver, Mapping):
                raise TypeError(
                    f"User '{chain[-1]}' forwards to '{target}', whose entry is "
                    f"{receiver!r} instead of a mapping"
                )
            chain.append(target)
            target = receiver["forward"]
