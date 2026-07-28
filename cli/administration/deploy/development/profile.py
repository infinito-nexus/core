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

    def instance(self) -> int:
        """Slot index of this checkout; 0 is the primary one.

        Bookkeeping only: the compose layering below keys off the concrete
        resources a worktree was handed, never off this number, so a stray
        slot cannot make compose demand a value nobody set.
        """
        raw = (os.environ.get("INFINITO_INSTANCE") or "0").strip()
        return int(raw) if raw.isdigit() else 0

    def shared_git_dir(self) -> str:
        """Path of the checkout's shared .git directory, empty when it owns one."""
        return (os.environ.get("INFINITO_GIT_COMMON_DIR") or "").strip()

    def shared_cache_network(self) -> str:
        """Docker network of a cache stack owned elsewhere, empty when unset."""
        return (os.environ.get("INFINITO_CACHE_NETWORK") or "").strip()

    def owns_cache_stack(self) -> bool:
        """True iff this instance runs the cache stack rather than sharing it."""
        return self.registry_cache_active() and not self.shared_cache_network()
