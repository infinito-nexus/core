"""Generate the licence-context page: in which context each role may be used.

Usage:
  python -m infinito_docs.generators.licensing --roles-dir DIR --output FILE

Every invokable role is listed. A role whose licence could not be resolved
appears under "Not yet determined" rather than being left out, because a gap
that is invisible reads as safe.
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from utils.licensing.contexts import CONTEXTS, UNKNOWN
    from utils.licensing.rights import DISCLAIMERS, DUTIES, GRANTS, NOT_GRANTED
    from utils.licensing.roles import Declared, declared, deploys_nothing
    from utils.roles.required_by_coverage import role_is_invokable
except ImportError:
    DECLARED_LICENCES = False
else:
    DECLARED_LICENCES = True

COLUMNS: tuple[tuple[str, str], ...] = (
    tuple(
        (field, field.replace("_", " ").capitalize())
        for field in GRANTS + DUTIES + DISCLAIMERS + NOT_GRANTED
    )
    if DECLARED_LICENCES
    else ()
)

ABSENT = """\
.. _generated-licensing:

Licence contexts
================

This release predates the per-role licence declarations, so there is nothing
to tabulate for it. The page exists because the table of contents references
it for every version; newer releases carry the matrix.
"""

HEADER = """\
.. _generated-licensing:

Licence contexts
================

The Infinito.Nexus licence governs this repository's own code. It says nothing
about the software a role deploys, and that is where a restriction on
commercial use usually sits. This page answers, per role, what the deployed
software's own licence allows.

Each role declares its licence in ``meta/<role>/license.yml``; the rights of a
named licence live once in ``meta/licenses.yml``. The context headings below
are derived from those rights, not declared, so a heading can never contradict
the matrix under it.

``yes`` means the licence grants the permission, imposes the duty, or
disclaims the liability named in the column; ``no`` means it does not. This
page is not legal advice.

"""

FOOTER = """
.. note::

   Generated from ``meta/<role>/license.yml`` and ``meta/licenses.yml``.
   Correct a row at its source, never here.
"""


def _mark(value: bool | None) -> str:
    """Return the cell for one boolean.

    Args:
        value: the right's value, or None when the licence is unresolved.

    A bare ``-`` would be read as a bullet marker and render as an empty
    cell, which is indistinguishable from a missing value.
    """
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _collect(
    roles_dir: Path,
) -> tuple[dict[str, list[tuple[str, Declared | None]]], list[str]]:
    """Group every invokable role by its derived licence context.

    Args:
        roles_dir: the repository's roles directory.

    Returns:
        The grouping, and the roles that declare they deploy no third-party
        software. Those carry no licence to classify, so listing them under
        "not yet determined" would report a gap where there is none.
    """
    grouped: dict[str, list[tuple[str, Declared | None]]] = {
        context.key: [] for context in CONTEXTS
    }
    nothing: list[str] = []
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir() or not role_is_invokable(role_dir.name):
            continue
        if deploys_nothing(role_dir):
            nothing.append(role_dir.name)
            continue
        entry = declared(role_dir)
        key = entry.context.key if entry is not None else UNKNOWN.key
        grouped[key].append((role_dir.name, entry))
    return grouped, nothing


def _row(name: str, entry: Declared | None) -> list[str]:
    """Return one matrix row.

    Args:
        name: the role name.
        entry: its declaration, or None when the role declares none.
    """
    spdx = entry.spdx if entry is not None and entry.spdx else "not determined"
    licence = f"`{spdx} <{entry.url}>`_" if entry is not None and entry.url else spdx
    rights = entry.rights if entry is not None else None
    return [
        f"``{name}``",
        licence,
        *[
            _mark(None if rights is None else bool(rights.get(field)))
            for field, _ in COLUMNS
        ],
    ]


def _section(context, entries: list[tuple[str, Declared | None]]) -> str:
    """Render one context's heading, verdict and matrix.

    Args:
        context: the context being rendered.
        entries: its roles, each with its declaration.
    """
    lines = [
        context.title,
        "-" * len(context.title),
        "",
        f"**Commercial use:** {context.commercial}.",
        "",
        f"**You owe:** {context.duties}.",
        "",
        ".. list-table::",
        "   :header-rows: 1",
        "   :stub-columns: 1",
        "",
    ]
    header = ["Role", "Licence", *[label for _, label in COLUMNS]]
    for row in (header, *(_row(name, entry) for name, entry in entries)):
        lines.append(f"   * - {row[0]}")
        lines += [f"     - {cell}" for cell in row[1:]]
    lines.append("")
    return "\n".join(lines)


def generate(roles_dir: Path, output: Path) -> int:
    """Write the licence-context page and return the number of roles on it.

    Args:
        roles_dir: the repository's roles directory.
        output: the ``.rst`` file to write.
    """
    grouped, nothing = _collect(roles_dir)
    sections = [
        _section(context, grouped[context.key])
        for context in CONTEXTS
        if grouped[context.key]
    ]
    if nothing:
        listed = ", ".join(f"``{role}``" for role in nothing)
        sections.append(
            "Deploying no third-party software\n"
            "---------------------------------\n\n"
            "These roles install nothing of their own, so the question this "
            f"page answers does not arise for them: {listed}.\n"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HEADER + "\n".join(sections) + FOOTER, encoding="utf-8")
    return sum(len(entries) for entries in grouped.values()) + len(nothing)


def main(argv=None):
    """Entry point.

    Args:
        argv: command line arguments, or None to read ``sys.argv``.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roles-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if not DECLARED_LICENCES:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(ABSENT, encoding="utf-8")
        print(f"licensing: release without declarations -> {args.output}")
        return 0
    count = generate(args.roles_dir, args.output)
    print(f"licensing: {count} roles -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
