"""Runtime-context helpers for the dev/CI compose stack."""

from __future__ import annotations

import os


def _declared(name: str) -> bool | None:
    """Explicit capability declaration, or None when it is left to the default."""
    raw = (os.environ.get(name) or "").strip()
    if raw == "true":
        return True
    if raw == "false":
        return False
    return None


class Profile:
    """Runtime identity and the capability decisions derived from it."""

    def is_ci(self) -> bool:
        """True when any standard CI signal is set."""
        return (
            os.environ.get("GITHUB_ACTIONS") == "true"
            or os.environ.get("INFINITO_RUNNING_ON_GITHUB") == "true"
            or os.environ.get("CI") == "true"
        )

    def runs_on_github(self) -> bool:
        """True on a real GitHub runner; act and generic CI are not that."""
        return os.environ.get("INFINITO_RUNNING_ON_GITHUB") == "true"

    def cache_stack_enabled(self) -> bool:
        """True iff the pull-through cache stack should be loaded."""
        declared = _declared("INFINITO_CACHE_STACK")
        return (not self.is_ci()) if declared is None else declared

    def image_mirror_enabled(self) -> bool:
        """True iff image references should be rewritten to the GHCR mirror."""
        return self.runs_on_github()

    def docker_root_ephemeral(self) -> bool:
        """True iff the docker data root may be wiped when the stack goes down."""
        return self.runs_on_github()

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
        return self.cache_stack_enabled() and not self.shared_cache_network()
