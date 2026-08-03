"""Default bundle limits for the CI deploy-matrix discovery.

Kept apart from :mod:`utils.github.variant.bundles`, which reaches yaml and
humanfriendly at import time: the env handlers that seed these defaults are
imported by the .env generator on the bare bootstrap python, where no
third-party module exists. This module must stay stdlib-only.
"""

from __future__ import annotations

DEFAULT_BUNDLE_SIZE = 3
DEFAULT_MAX_STORAGE = "350GB"
