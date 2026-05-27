"""Dotted-path recursive key extraction."""

from __future__ import annotations


def recursive_keys(d, prefix: str = "") -> set[str]:
    """Return every dotted key path reachable from a nested mapping."""
    keys: set[str] = set()
    if isinstance(d, dict):
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            keys.add(full)
            keys.update(recursive_keys(v, full))
    return keys
