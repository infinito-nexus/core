"""Render complexity rows as a counts table, JSON, or bare role names."""

from __future__ import annotations

import json
import unicodedata
from typing import TYPE_CHECKING

from utils.cache.yaml import dump_yaml_str
from utils.symbol_glossary import to_emoji

if TYPE_CHECKING:
    from .model import ComplexityRow

DNA_DISPLAY_LEN = 10


def _char_width(ch: str) -> int:
    """Terminal cell width of one character: 0 for combining marks / variation
    selectors / ZWJ, 2 for emoji and East-Asian wide glyphs, else 1."""
    o = ord(ch)
    if o == 0x200D or 0xFE00 <= o <= 0xFE0F or 0x1F3FB <= o <= 0x1F3FF:
        return 0
    if (
        0x1F000 <= o <= 0x1FAFF
        or 0x2600 <= o <= 0x27BF
        or 0x2B00 <= o <= 0x2BFF
        or unicodedata.east_asian_width(ch) in ("W", "F")
    ):
        return 2
    return 1


def _dwidth(text: str) -> int:
    """Display width of *text* in terminal cells (emoji count as 2)."""
    return sum(_char_width(ch) for ch in text)


def _variant_cell(row: ComplexityRow) -> str:
    return "" if row.variant is None else str(row.variant)


_LIFECYCLE_STAGES = (
    "planned",
    "pre-alpha",
    "alpha",
    "beta",
    "rc",
    "stable",
    "maintenance",
    "deprecated",
    "eol",
)
_LIFECYCLE_SYMBOLS: dict[str, str] = {s: to_emoji(s) for s in _LIFECYCLE_STAGES}

_HEADER_NAMES = (
    "row",
    "id",
    "name",
    "lifecycle",
    "variant",
    "integrated",
    "variants",
    "bundles",
    "jobs",
    "compose",
    "swarm",
    "stack",
    "host",
    "test_compose",
    "test_swarm",
    "test_host",
    "embeds_direct",
    "embeds",
    "consumers_direct",
    "consumers",
    "weight",
    "random",
    "dna",
    "clone",
    "siblings",
    "covered_by",
)
_HEADER_SYMBOLS: dict[str, str] = {name: to_emoji(name) for name in _HEADER_NAMES}


def _bool_cell(value: bool, *, symbol: bool = False) -> str:
    if symbol:
        return to_emoji("enabled") if value else to_emoji("disabled")
    return "true" if value else "false"


def _lifecycle_cell(stage: str, *, symbol: bool = False) -> str:
    return _LIFECYCLE_SYMBOLS.get(stage, stage) if symbol else stage


def _header(name: str, *, symbol: bool) -> str:
    """With ``symbol`` the header is the emoji alone (compact); the column name
    falls back in only when no emoji is mapped."""
    if not symbol:
        return name
    return _HEADER_SYMBOLS.get(name, name)


_COLUMN_DOC: dict[str, str] = {
    "row": "line number in this rendering",
    "id": "position in sort order",
    "name": "role id",
    "lifecycle": "maturity stage (see Lifecycle below)",
    "variant": "meta/variants.yml index of this row",
    "integrated": "row's service map keeps at least one foreign service enabled",
    "variants": "number of variants the role has",
    "bundles": "CI jobs this row maps to in the deploy mode",
    "jobs": "running total of bundles down the rows",
    "compose": "exercised by the compose test-deploy matrix",
    "swarm": "exercised by the swarm test-deploy matrix",
    "stack": "ships its own container stack (compose template)",
    "host": "configures the host instead of shipping a stack",
    "test_compose": "compose minus meta/tests.yml skip",
    "test_swarm": "swarm minus meta/tests.yml skip",
    "test_host": "host minus meta/tests.yml skip",
    "embeds_direct": "service roles it embeds directly",
    "embeds": "service roles it embeds transitively",
    "consumers_direct": "roles that embed it directly",
    "consumers": "roles that embed it transitively",
    "weight": "sum of the four count columns",
    "random": "per-row display nonce",
    "dna": "cluster key shared by same-service-set roles",
    "clone": "another role with the same dna carries more weight",
    "siblings": "other roles sharing the dna",
    "covered_by": "id of an earlier row that already embeds it (0 = green)",
}

_LIFECYCLE_DOC: dict[str, str] = {
    "planned": "on the roadmap, no code yet",
    "pre-alpha": "scaffolding, too unstable to test",
    "alpha": "deploys end-to-end with a smoke spec",
    "beta": "documented integrations tested",
    "rc": "burn-in on production, intends stable",
    "stable": "shipped in a release without a hotfix",
    "maintenance": "stable coverage, feature-frozen",
    "deprecated": "kept for compatibility, do not adopt",
    "eol": "end of life: shipped but not tested or maintained",
}


def _symbol_legend(names: list[str], rows: list[ComplexityRow]) -> list[str]:
    """Grouped legend, one entry per line: symbol, label, explanation. The
    symbol is placed LAST so the label and doc columns (both pure ASCII) stay
    flush regardless of how wide the terminal renders each emoji; only the
    trailing symbol can shift a cell, at the line end where it does not disturb
    the grid. Only the columns rendered and lifecycle stages present are listed."""
    columns = [
        (_HEADER_SYMBOLS[name], name, _COLUMN_DOC.get(name, ""))
        for name in names
        if name in _HEADER_SYMBOLS
    ]
    flags = [("✅", "true", "the flag is set"), ("❌", "false", "the flag is not set")]
    present = {r.lifecycle for r in rows}
    lifecycle = [
        (symbol, stage, _LIFECYCLE_DOC.get(stage, ""))
        for stage, symbol in _LIFECYCLE_SYMBOLS.items()
        if stage in present
    ]

    groups = [("Columns", columns), ("Flags", flags)]
    if lifecycle:
        groups.append(("Lifecycle", lifecycle))

    entries = [entry for _, group in groups for entry in group]
    label_w = max(len(label) for _, label, _ in entries)
    doc_w = max(len(doc) for _, _, doc in entries)

    lines = ["", "Legend:"]
    for title, group in groups:
        lines.append(f"    {title}:")
        lines.extend(
            f"        {label.ljust(label_w)}  {doc.ljust(doc_w)}  {sym}"
            for sym, label, doc in group
        )
    return lines


def render_table(rows: list[ComplexityRow], *, symbol: bool = False) -> str:
    """Counts only (plus the short ``dna`` and the sibling count). Use
    ``--format json`` for the full role and sibling name lists. With
    ``symbol=True`` the headers are emoji-only (compact), the
    boolean/lifecycle cells render as emojis, and a legend is appended."""
    if not rows:
        return ""

    raw = [
        ("row", ">", [str(r.row) for r in rows]),
        ("id", ">", [str(r.id) for r in rows]),
        ("name", "<", [r.name for r in rows]),
        ("lifecycle", "<", [_lifecycle_cell(r.lifecycle, symbol=symbol) for r in rows]),
        *(
            [("variant", ">", [_variant_cell(r) for r in rows])]
            if any(r.variant is not None for r in rows)
            else []
        ),
        ("integrated", ">", [_bool_cell(r.integrated, symbol=symbol) for r in rows]),
        ("variants", ">", [str(r.variants) for r in rows]),
        ("bundles", ">", [str(r.bundles) for r in rows]),
        ("jobs", ">", [str(r.jobs) for r in rows]),
        ("compose", ">", [_bool_cell(r.compose, symbol=symbol) for r in rows]),
        ("swarm", ">", [_bool_cell(r.swarm, symbol=symbol) for r in rows]),
        ("host", ">", [_bool_cell(r.host, symbol=symbol) for r in rows]),
        ("stack", ">", [_bool_cell(r.stack, symbol=symbol) for r in rows]),
        (
            "test_compose",
            ">",
            [_bool_cell(r.test_compose, symbol=symbol) for r in rows],
        ),
        ("test_swarm", ">", [_bool_cell(r.test_swarm, symbol=symbol) for r in rows]),
        ("test_host", ">", [_bool_cell(r.test_host, symbol=symbol) for r in rows]),
        ("embeds_direct", ">", [str(r.embeds_direct) for r in rows]),
        ("embeds", ">", [str(r.embeds) for r in rows]),
        ("consumers_direct", ">", [str(r.consumers_direct) for r in rows]),
        ("consumers", ">", [str(r.consumers) for r in rows]),
        ("weight", ">", [str(r.weight) for r in rows]),
        ("random", ">", [str(r.random) for r in rows]),
        ("dna", "<", [r.dna[:DNA_DISPLAY_LEN] for r in rows]),
        ("clone", ">", [_bool_cell(r.clone, symbol=symbol) for r in rows]),
        ("siblings", ">", [str(len(r.siblings)) for r in rows]),
        ("covered_by", ">", [str(r.covered_by) for r in rows]),
    ]
    cols = [(_header(name, symbol=symbol), align, cells) for name, align, cells in raw]
    widths = [
        max(_dwidth(title), *(_dwidth(c) for c in cells)) for title, _, cells in cols
    ]

    def _line(values: list[str]) -> str:
        parts = []
        for v, (_, align, _), w in zip(values, cols, widths, strict=True):
            gap = " " * max(w - _dwidth(v), 0)
            parts.append(v + gap if align == "<" else gap + v)
        return "  ".join(parts)

    lines = [
        _line([title for title, _, _ in cols]),
        "  ".join("-" * w for w in widths),
    ]
    lines.extend(_line([cells[i] for _, _, cells in cols]) for i in range(len(rows)))
    if symbol:
        lines.extend(_symbol_legend([name for name, _, _ in raw], rows))
    return "\n".join(lines)


def _payload(rows: list[ComplexityRow]) -> list[dict]:
    return [
        {
            "row": r.row,
            "id": r.id,
            "name": r.name,
            "lifecycle": r.lifecycle,
            "variant": r.variant,
            "integrated": r.integrated,
            "variants": r.variants,
            "bundles": r.bundles,
            "jobs": r.jobs,
            "compose": r.compose,
            "swarm": r.swarm,
            "host": r.host,
            "stack": r.stack,
            "test_compose": r.test_compose,
            "test_swarm": r.test_swarm,
            "test_host": r.test_host,
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
            "dna": r.dna,
            "clone": r.clone,
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
