from __future__ import annotations


class ServicesResolutionError(RuntimeError):
    """Raised when shared service resolution fails (e.g., missing mapping, invalid config)."""
