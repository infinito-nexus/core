"""Runtime-context helpers for the dev/CI compose stack."""

from __future__ import annotations

import os


class Profile:
    """Runtime-context flags consumed by the compose wrapper."""

    def is_ci(self) -> bool:
        """True when any standard CI signal is set."""
        return (
            os.environ.get("GITHUB_ACTIONS") == "true"
            or os.environ.get("INFINITO_RUNNING_ON_GITHUB") == "true"
            or os.environ.get("CI") == "true"
        )

    def registry_cache_active(self) -> bool:
        """True iff the cache stack should be loaded (local dev only)."""
        return not self.is_ci()
