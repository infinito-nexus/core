"""Render complexity rows as a counts table, JSON, or bare role names."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import ComplexityRow

BASE_DISPLAY_LEN = 10


def render_table(rows: list[ComplexityRow]) -> str:
    """Counts only (plus the short ``base`` and the sibling count). Use
    ``--format json`` for the full role and sibling name lists."""
    if not rows:
        return ""
    cols = [
        ("name", "<", [r.name for r in rows]),
        ("embeds_direct", ">", [str(r.embeds_direct) for r in rows]),
        ("embeds", ">", [str(r.embeds) for r in rows]),
        ("consumers_direct", ">", [str(r.consumers_direct) for r in rows]),
        ("consumers", ">", [str(r.consumers) for r in rows]),
        ("total", ">", [str(r.total) for r in rows]),
        ("base", "<", [r.base[:BASE_DISPLAY_LEN] for r in rows]),
        ("siblings", ">", [str(len(r.siblings)) for r in rows]),
    ]
    widths = [max(len(title), *(len(c) for c in cells)) for title, _, cells in cols]

    def _line(values: list[str]) -> str:
        return "  ".join(
            f"{v:{align}{w}}"
            for v, (_, align, _), w in zip(values, cols, widths, strict=True)
        )

    lines = [
        _line([title for title, _, _ in cols]),
        "  ".join("-" * w for w in widths),
    ]
    lines.extend(_line([cells[i] for _, _, cells in cols]) for i in range(len(rows)))
    return "\n".join(lines)


def render_json(rows: list[ComplexityRow]) -> str:
    payload = [
        {
            "name": r.name,
            "embeds_direct": r.embeds_direct,
            "services_direct": r.services_direct,
            "embeds": r.embeds,
            "services": r.services,
            "consumers_direct": r.consumers_direct,
            "consumed_by_direct": r.consumed_by_direct,
            "consumers": r.consumers,
            "consumed_by": r.consumed_by,
            "total": r.total,
            "base": r.base,
            "siblings": r.siblings,
        }
        for r in rows
    ]
    return json.dumps(payload, indent=2)


def render_string(rows: list[ComplexityRow]) -> str:
    return "\n".join(r.name for r in rows)
