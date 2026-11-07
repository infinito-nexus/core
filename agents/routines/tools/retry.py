"""Retry decision by failure class: a deterministic failure is never retried, a
flaky one is retried once. The class comes from the failure-class node; this
node only turns it and the retries already spent into the retry verdict.
"""

from __future__ import annotations

_FLAKY = "flaky"
_FLAKY_RETRIES = 1


def should_retry(failure_class: str, *, retries_done: int) -> bool:
    """Return whether a failure of ``failure_class`` is retried now.

    Only a flaky failure is retried, and only once; every other class,
    deterministic included, never is.

    Args:
        failure_class: the classified failure, e.g. ``deterministic`` or
            ``flaky``.
        retries_done: how often this failure was already retried.
    """
    return failure_class.strip().lower() == _FLAKY and retries_done < _FLAKY_RETRIES
