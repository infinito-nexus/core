"""Errors that MUST survive a best-effort render.

`utils.cache.base._render_with_templar` and the two templar helpers behind it
swallow every exception on purpose: a meta payload renders in rounds, and an
expression that cannot resolve yet has to come back unchanged rather than abort
the round.

That contract is wrong for one class of failure. When a value could not be
measured and substituting one would be a guess, silence turns a loud stop into
a wrong number nobody sees. Such a failure raises from here and every render
layer re-raises it untouched.

No ansible import: `utils.cache.base` deliberately carries none, and the env
generator imports parts of `utils` on hosts that have no ansible installed.
"""

from __future__ import annotations


class UnresolvableValueError(Exception):
    """A value could not be determined and MUST NOT be substituted."""


def is_unresolvable(exc: BaseException | None) -> bool:
    """True when `exc` is, or was caused by, an `UnresolvableValueError`.

    Ansible wraps an exception raised inside a lookup into its own error type,
    so the original is reachable only through the `__cause__` / `__context__`
    chain. The walk is cycle-guarded because a re-raise can make that chain
    point back at itself.
    """
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, UnresolvableValueError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False
