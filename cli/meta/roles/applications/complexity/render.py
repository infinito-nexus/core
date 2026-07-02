"""Render complexity rows as a counts table, JSON, or bare role names."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from utils.cache.yaml import dump_yaml_str

if TYPE_CHECKING:
    from .model import ComplexityRow

BASE_DISPLAY_LEN = 10


def _variant_cell(row: ComplexityRow) -> str:
    return "" if row.variant is None else str(row.variant)


def _bool_cell(value: bool) -> str:
    return "true" if value else "false"


def render_table(rows: list[ComplexityRow]) -> str:
    """Counts only (plus the short ``base`` and the sibling count). Use
    ``--format json`` for the full role and sibling name lists."""
    if not rows:
        return ""
    cols = [
        ("row", ">", [str(r.row) for r in rows]),
        ("id", ">", [str(r.id) for r in rows]),
        ("name", "<", [r.name for r in rows]),
        ("lifecycle", "<", [r.lifecycle for r in rows]),
        *(
            [("variant", ">", [_variant_cell(r) for r in rows])]
            if any(r.variant is not None for r in rows)
            else []
        ),
        ("variants", ">", [str(r.variants) for r in rows]),
        ("bundles", ">", [str(r.bundles) for r in rows]),
        ("jobs", ">", [str(r.jobs) for r in rows]),
        ("compose", ">", [_bool_cell(r.compose) for r in rows]),
        ("swarm", ">", [_bool_cell(r.swarm) for r in rows]),
        ("embeds_direct", ">", [str(r.embeds_direct) for r in rows]),
        ("embeds", ">", [str(r.embeds) for r in rows]),
        ("consumers_direct", ">", [str(r.consumers_direct) for r in rows]),
        ("consumers", ">", [str(r.consumers) for r in rows]),
        ("weight", ">", [str(r.weight) for r in rows]),
        ("random", ">", [str(r.random) for r in rows]),
        ("base", "<", [r.base[:BASE_DISPLAY_LEN] for r in rows]),
        ("siblings", ">", [str(len(r.siblings)) for r in rows]),
        ("covered_by", ">", [str(r.covered_by) for r in rows]),
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


def _payload(rows: list[ComplexityRow]) -> list[dict]:
    return [
        {
            "row": r.row,
            "id": r.id,
            "name": r.name,
            "lifecycle": r.lifecycle,
            "variant": r.variant,
            "variants": r.variants,
            "bundles": r.bundles,
            "jobs": r.jobs,
            "compose": r.compose,
            "swarm": r.swarm,
            "embeds_direct": r.embeds_direct,
            "services_direct": r.services_direct,
            "embeds": r.embeds,
            "services": r.services,
            "consumers_direct": r.consumers_direct,
            "consumed_by_direct": r.consumed_by_direct,
            "consumers": r.consumers,
            "consumed_by": r.consumed_by,
            "weight": r.weight,
            "random": r.random,
            "base": r.base,
            "siblings": r.siblings,
            "covered_by": r.covered_by,
        }
        for r in rows
    ]


def render_json(rows: list[ComplexityRow]) -> str:
    return json.dumps(_payload(rows), indent=2)


def render_yaml(rows: list[ComplexityRow]) -> str:
    return dump_yaml_str(_payload(rows)).rstrip("\n")


def render_string(rows: list[ComplexityRow]) -> str:
    return "\n".join(
        r.name if r.variant is None else f"{r.name}#{r.variant}" for r in rows
    )
