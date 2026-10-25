"""Classify a rate-limit failure across a run's jobs: which failing jobs hit a
registry rate limit, whether each went through the mirror or the cache, and
which jobs did not fail. A retry is no fix; the report shows why some jobs were
protected and others exposed.
"""

from __future__ import annotations

import re

_RATE_LIMIT = re.compile(
    r"toomanyrequests|too many requests|\b429\b|pull rate limit|rate limit exceeded",
    re.IGNORECASE,
)
_MIRROR = re.compile(r"\bmirror\b", re.IGNORECASE)
_CACHE = re.compile(r"\bcache\b", re.IGNORECASE)


def classify(jobs: dict[str, str]) -> dict:
    """Return the rate-limit verdict over ``jobs``.

    Args:
        jobs: a mapping of job name to that job's captured log.

    Returns:
        a mapping with ``rate_limited`` (the jobs whose log shows a registry
        rate limit), ``via_mirror`` and ``via_cache`` (the rate-limited jobs
        whose log names the mirror or the cache pull path) and ``passed`` (the
        jobs with no rate-limit signal).
    """
    rate_limited: list[str] = []
    via_mirror: list[str] = []
    via_cache: list[str] = []
    passed: list[str] = []
    for name, log in jobs.items():
        if not _RATE_LIMIT.search(log):
            passed.append(name)
            continue
        rate_limited.append(name)
        if _MIRROR.search(log):
            via_mirror.append(name)
        if _CACHE.search(log):
            via_cache.append(name)
    return {
        "rate_limited": rate_limited,
        "via_mirror": via_mirror,
        "via_cache": via_cache,
        "passed": passed,
    }
