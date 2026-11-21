"""A block between two marker lines that the docs build renders and git never holds."""

from __future__ import annotations


def replace_block(text: str, block: str, *, begin: str, end: str, doc: str) -> str:
    """*text* with everything between the markers replaced by *block*.

    Args:
        text: the document.
        block: the rendered block.
        begin: the opening marker line.
        end: the closing marker line.
        doc: the document's repository path, named in the error.

    Raises:
        ValueError: the markers are missing, repeated or out of order.
    """
    lines = text.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.strip() == begin]
    ends = [i for i, line in enumerate(lines) if line.strip() == end]
    if len(begins) != 1 or len(ends) != 1 or begins[0] > ends[0]:
        raise ValueError(f"{doc} needs exactly one {begin} line before one {end} line")
    head = "".join(lines[: begins[0] + 1])
    tail = "".join(lines[ends[0] :])
    return f"{head}\n{block}\n\n{tail}"


def committed_block_problems(text: str, *, begin: str, end: str) -> list[str]:
    """What keeps *text* from carrying an empty, well-placed marker pair.

    Args:
        text: the committed document.
        begin: the opening marker line.
        end: the closing marker line.

    Returns:
        One line per problem: a missing, repeated or reversed marker, or a
        non-blank line between the markers. Empty when the file is clean.
    """
    lines = text.splitlines()
    begins = [n for n, line in enumerate(lines, start=1) if line.strip() == begin]
    ends = [n for n, line in enumerate(lines, start=1) if line.strip() == end]
    if len(begins) != 1 or len(ends) != 1:
        found = f"found {len(begins)} and {len(ends)}"
        return [f"expected one {begin} and one {end} line, {found}"]
    if begins[0] > ends[0]:
        return [f"{begin} on line {begins[0]} follows {end} on line {ends[0]}"]
    return [
        f"line {number} is committed between the markers: {lines[number - 1]!r}"
        for number in range(begins[0] + 1, ends[0])
        if lines[number - 1].strip()
    ]
