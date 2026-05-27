"""Interactive operator prompts for the credentials CLI."""

from __future__ import annotations


def ask_for_confirmation(key: str) -> bool:
    """Prompt the user for confirmation to overwrite an existing value."""
    confirmation = (
        input(f"Are you sure you want to overwrite the value for '{key}'? (y/n): ")
        .strip()
        .lower()
    )
    return confirmation == "y"
