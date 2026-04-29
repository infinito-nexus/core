"""In-process caches for runtime data (applications, users, domains).

Domain modules:

- ``utils.cache.base``         — cross-cutting helpers (constants,
  deep-merge, signatures, render machinery).
- ``utils.cache.applications`` — variants + ``get_merged_applications``
  (ansible-free at import time, runner-host friendly).
- ``utils.cache.users``        — ``get_user_defaults``, ``get_merged_users``.
- ``utils.cache.domains``      — ``get_merged_domains``.
- ``utils.cache.yaml``         — process-wide ``load_yaml`` /
  ``load_yaml_any`` parser cache shared by everything that reads YAML
  off-disk.
- ``utils.cache.files``        — process-wide project-tree walk +
  file-content cache (``read_text``, ``iter_project_files``,
  ``iter_non_ignored_files``).
- ``utils.cache.gitignore``    — cached ``.gitignore`` pattern loader
  + path matcher used by lint/integration tests that need a
  "files git would track" view without spawning git.

Use the domain module directly. The package-level
``_reset_cache_for_tests`` clears every domain's caches plus the shared
fingerprint memo in one call — preferred over hand-rolling N
``_reset()`` calls per test fixture.
"""

from __future__ import annotations


def _reset_cache_for_tests() -> None:
    """Orchestrate per-domain cache resets plus the shared fingerprint
    memo. Test fixtures rely on a single entry point so they can stay
    agnostic of how the cache is partitioned across modules."""
    from . import applications, base, domains, files, gitignore, users
    from . import yaml as _yaml_cache

    applications._reset()
    users._reset()
    domains._reset()
    base._reset()
    _yaml_cache._reset()
    files._reset()
    gitignore._reset()
