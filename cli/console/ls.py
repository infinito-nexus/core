from __future__ import annotations

from cli.core.colors import Style, color_text
from cli.core.discovery import iter_dir_entries
from cli.core.help import _entry_description, _entry_emoji

from .constants import CLI_ROOT, LS_DESC_LIMIT


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def do_ls(current: list[str]) -> None:
    entries = iter_dir_entries(CLI_ROOT, tuple(current))
    if not entries:
        print(color_text("(empty)", Style.DIM))
        return
    # Folders (categories) first, then commands; within each group keep
    # the alphabetical order `iter_dir_entries` already established.
    ordered = sorted(entries, key=lambda e: (e.is_command, e.name))
    max_name = max(len(entry.name) for entry in ordered)
    for entry in ordered:
        emoji = _entry_emoji(entry)
        desc = truncate(_entry_description(CLI_ROOT, entry), LS_DESC_LIMIT)
        print(f"  {emoji}  {entry.name.ljust(max_name)}  {color_text(desc, Style.DIM)}")
