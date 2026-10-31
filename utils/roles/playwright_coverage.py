"""Which sweep row first triggers each Playwright spec.

A spec runs when the role that ships it is deployed, so its first trigger is
the first row of the sweep carrying that role. Shared by the reporting command
and the integration test that holds the line, so both read one answer.

Two rows are not holes. A row the budget drops still counts: the cut is a
property of the runner's wall clock, not of the coverage the matrix was built
to give. And a role outside the tested lifecycle envelope is excluded on
purpose, so listing its specs beside the real holes is how a reader ends up
writing manual checks for a role nobody deploys.

The caller supplies the entries and the chunk plan, which keeps this module
free of the CI command layer that builds them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from utils.roles.lifecycle import tested_lifecycles
from utils.roles.meta_lookup import get_role_lifecycle

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

SPEC_GLOB = "*/files/playwright/*.js"


class Triggered(NamedTuple):
    """One spec and the row that first runs it."""

    role: str
    spec: str
    variant: str
    mode: str
    chunk: str


class Excluded(NamedTuple):
    """One spec of a role the sweep does not test, and that role's lifecycle."""

    role: str
    spec: str
    lifecycle: str


class Coverage(NamedTuple):
    triggered: list[Triggered]
    uncovered: list[tuple[str, str]]
    excluded: list[Excluded]


def specs_by_role(roles_dir: Path) -> dict[str, list[str]]:
    """Return ``{role: [spec file name, ...]}`` for every role shipping specs."""
    found: dict[str, list[str]] = {}
    for path in sorted(roles_dir.glob(SPEC_GLOB)):
        found.setdefault(path.parts[-4], []).append(path.name)
    return found


def first_rows(entries: Iterable[Mapping[str, str]]) -> dict[str, Mapping[str, str]]:
    """The first entry of the sweep per role, in plan order."""
    first: dict[str, Mapping[str, str]] = {}
    for entry in entries:
        first.setdefault(entry["apps"], entry)
    return first


def chunk_index(plan: Iterable[Sequence[Mapping[str, str]]] | None) -> dict[int, str]:
    """Map each entry's identity to its chunk number, in one pass.

    Resolving the chunk by scanning the plan per row is quadratic, and the
    plan holds the very objects the entry list does, so identity indexes them
    without needing the rows to be hashable or comparable.
    """
    index: dict[int, str] = {}
    for number, chunk in enumerate(plan or []):
        for entry in chunk:
            index[id(entry)] = str(number)
    return index


def classify(
    by_role: Mapping[str, list[str]],
    first: Mapping[str, Mapping[str, str]],
    chunks: Mapping[int, str],
    roles_dir: Path,
) -> Coverage:
    """Split every spec into triggered, genuinely uncovered, and excluded."""
    tested = tested_lifecycles()
    triggered: list[Triggered] = []
    uncovered: list[tuple[str, str]] = []
    excluded: list[Excluded] = []
    for role, names in sorted(by_role.items()):
        entry = first.get(role)
        if entry is None:
            lifecycle = get_role_lifecycle(roles_dir / role, role_name=role) or "unset"
            if lifecycle not in tested:
                excluded.extend(Excluded(role, name, lifecycle) for name in names)
            else:
                uncovered.extend((role, name) for name in names)
            continue
        chunk = chunks.get(id(entry), "-")
        triggered.extend(
            Triggered(
                role, name, entry.get("variant", ""), entry.get("mode", ""), chunk
            )
            for name in names
        )
    return Coverage(triggered, uncovered, excluded)
