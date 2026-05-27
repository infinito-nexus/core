from __future__ import annotations


class CombinedResolutionError(RuntimeError):
    """Raised when combined run_after + dependencies resolution fails (e.g., cycle detected)."""
