"""Default bundle limits for the CI deploy-matrix discovery.

Kept apart from :mod:`utils.github.variant.bundles`, which reaches yaml and
humanfriendly at import time: the env handlers that seed these defaults are
imported by the .env generator on the bare bootstrap python, where no
third-party module exists. This module must stay stdlib-only.

``DEFAULT_MAX_STORAGE`` is also a runtime proxy: hosted runners kill jobs at
6 h, and heavy multi-round roles (nextcloud) only fit that wall with <= 2
variants per bundle — the cap must stay below their lightest 3-variant sum or
the greedy packer overshoots.
"""

from __future__ import annotations

DEFAULT_BUNDLE_SIZE = 3
DEFAULT_MAX_STORAGE = "330GB"
