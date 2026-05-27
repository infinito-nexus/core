"""CLI ``--set`` override parsing and per-key resolution."""

from __future__ import annotations


def parse_overrides(pairs: list[str]) -> dict[str, str]:
    """Parse ``--set key=value`` pairs into a dict. Supports both
    ``credentials.key=val`` and ``key=val`` (short) forms."""
    out: dict[str, str] = {}
    for pair in pairs:
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def override_for(
    app_id: str, key: str, overrides: dict[str, str], *, is_primary: bool
) -> str | None:
    """Resolve overrides for a credential key.

    Supported forms:
      - ``applications.<app_id>.credentials.<key>=...``
      - ``<app_id>.credentials.<key>=...``
    Backwards compatible (PRIMARY app only):
      - ``credentials.<key>=...``
      - ``<key>=...``
    """
    v = overrides.get(f"applications.{app_id}.credentials.{key}")
    if v is not None:
        return v
    v = overrides.get(f"{app_id}.credentials.{key}")
    if v is not None:
        return v
    if is_primary:
        v = overrides.get(f"credentials.{key}")
        if v is not None:
            return v
        v = overrides.get(key)
        if v is not None:
            return v
    return None
