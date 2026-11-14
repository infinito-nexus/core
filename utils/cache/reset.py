from __future__ import annotations

from utils.domains import application_domain_index

from . import applications, base, domains, files, gitignore, users
from . import yaml as _yaml_cache


def _reset_cache_for_tests() -> None:
    """Orchestrate per-domain cache resets plus the shared fingerprint
    memo. Test fixtures rely on a single entry point so they can stay
    agnostic of how the cache is partitioned across modules."""
    application_domain_index._reset()
    applications._reset()
    users._reset()
    domains._reset()
    base._reset()
    _yaml_cache._reset()
    files._reset()
    gitignore._reset()
