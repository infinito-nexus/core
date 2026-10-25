"""Retry decision by failure class: a deterministic failure is never retried, a
flaky one is retried once. The class comes from the failure-class node; this
node only turns it into the retry verdict.
"""

from __future__ import annotations

_FLAKY = "flaky"


def should_retry(failure_class: str) -> bool:
    """Return whether a failure of ``failure_class`` is retried.

    Only a flaky failure is retried (once); every other class, deterministic
    included, is not.

    Args:
        failure_class: the classified failure, e.g. ``deterministic`` or
            ``flaky``.
    """
    return failure_class.strip().lower() == _FLAKY
