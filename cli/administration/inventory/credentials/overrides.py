"""CLI ``--set`` override parsing and per-key resolution."""

from __future__ import annotations

from utils.manager.credential_key import (
    OVERRIDE_ROOT,
    OVERRIDE_SECTION,
    override_key,
    split_override_key,
)

__all__ = ["override_for", "override_key", "parse_overrides", "split_override_key"]


def parse_overrides(pairs: list[str]) -> dict[str, str]:
    """Parse ``--set <key>=<value>`` pairs into a dict.

    Args:
        pairs: raw ``key=value`` strings from the command line.

    Every key MUST be the fully qualified form :func:`override_key` builds; a
    short form is rejected rather than guessed at, because the same short key
    names different credentials on different apps.
    """
    out: dict[str, str] = {}
    prefix = f"{OVERRIDE_ROOT}."
    section = f".{OVERRIDE_SECTION}."
    for pair in pairs:
        raw_key, value = pair.split("=", 1)
        key = raw_key.strip()
        if not key.startswith(prefix) or section not in key:
            raise SystemExit(
                f"--set {key}: expected "
                f"{OVERRIDE_ROOT}.<app_id>.{OVERRIDE_SECTION}.<key>=<value>"
            )
        out[key] = value.strip()
    return out


def override_for(app_id: str, key: str, overrides: dict[str, str]) -> str | None:
    """The override value for one credential, or None when unset.

    Args:
        app_id: application the credential belongs to.
        key: dotted path inside the schema's ``credentials`` node.
        overrides: parsed ``--set`` pairs.
    """
    return overrides.get(override_key(app_id, key))
