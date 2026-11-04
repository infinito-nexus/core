from __future__ import annotations

import logging
import re
from itertools import pairwise
from pathlib import Path

DEFAULT_MAX_NAV_DEPTH = 4
MAX_HEADING_LEVEL = 0

logger = logging.getLogger(__name__)

_MD_HEADING = re.compile(r"^(#+)(.*?)$")
_RST_UNDERLINE = re.compile(r"[-=~^+\"'`]+")


def natural_sort_key(text):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", text)]


def _markdown_headings(lines, max_level):
    headings = []
    in_code_block = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        match = None if in_code_block else _MD_HEADING.match(line)
        if match and len(match.group(1)) <= max_level:
            text = match.group(2).strip()
            anchor = re.sub(r"[^a-z0-9\-]", "", re.sub(r"\s+", "-", text.lower()))
            headings.append(
                {"level": len(match.group(1)), "text": text, "anchor": anchor}
            )
    return headings


def _rst_headings(lines):
    return [
        {"level": 1, "text": text.strip(), "anchor": ""}
        for text, underline in pairwise(lines)
        if len(underline) >= 3 and _RST_UNDERLINE.fullmatch(underline)
    ]


def extract_headings_from_file(filepath, max_level=MAX_HEADING_LEVEL):
    """Return the headings of a Markdown or reStructuredText file.

    Args:
        filepath: file to scan.
        max_level: deepest Markdown heading level to keep; ``0`` keeps all.

    Returns:
        ``{"level", "text", "anchor"}`` dicts in file order. An ``index.rst``
        without headings falls back to the ``README.md`` beside it.
    """
    path = Path(filepath)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Error reading %s: %s", path, exc)
        lines = []

    suffix = path.suffix.lower()
    if suffix == ".md":
        headings = _markdown_headings(lines, max_level or 9999)
    elif suffix == ".rst":
        headings = _rst_headings(lines)
    else:
        headings = []

    readme = path.with_name("README.md")
    if not headings and path.name.lower() == "index.rst" and readme.is_file():
        return extract_headings_from_file(readme, max_level)
    return headings


def group_headings(headings):
    tree = []
    stack = []
    for heading in headings:
        heading["children"] = []
        while stack and stack[-1]["level"] >= heading["level"]:
            stack.pop()
        (stack[-1]["children"] if stack else tree).append(heading)
        stack.append(heading)
    return tree


def sort_tree(tree):
    tree.sort(
        key=lambda x: (
            x.get("priority", 1),
            natural_sort_key(x.get("filename", x["text"])),
        )
    )
    for item in tree:
        if item.get("children"):
            sort_tree(item["children"])
