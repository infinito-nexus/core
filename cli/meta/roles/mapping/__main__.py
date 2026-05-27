"""CLI inspector for the role-file mapping SPOT.

Renders :data:`utils.roles.mapping.ROLE_FILES` in a human-readable form
so contributors can see at a glance which role files apply to which
role types, whether each is mandatory, allowed, or a type marker, and
which dotted-path entries are required inside each file.

Subcommands
-----------

``files``   : list every role file with its per-type policy.
``types``   : list every role type with the files it MUST / MAY ship.
``markers`` : list the marker entries that drive
              :func:`utils.roles.type.get_role_types` (which dotted
              path in which file decides each type).

Filtering
---------

``--type <ROLE_TYPE>`` narrows every subcommand to a single role type.
The default lists every type.

Output
------

``--format text`` (default) renders coloured / icon-prefixed plain
text suitable for terminals. ``--format json`` emits a stable
machine-readable structure for piping into ``jq`` or similar.

Examples::

    python -m cli.meta.roles.mapping files
    python -m cli.meta.roles.mapping files --type application
    python -m cli.meta.roles.mapping types --type system-service
    python -m cli.meta.roles.mapping markers --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

from utils.roles.mapping import (
    ROLE_FILES,
    ROLE_TYPE_ALL,
    ROLE_TYPES,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

_FORMATS = ("text", "json")


# === Resolution helpers =====================================================


def _entries_for_type(file_entry: dict, role_type: str) -> dict | None:
    """Return the type-scoping entry that applies to *role_type* in
    *file_entry*. Concrete-type entries override the wildcard fallback;
    when neither matches the file is implicitly forbidden.
    """
    types = file_entry.get("types") or []
    wildcard: dict | None = None
    for entry in types:
        if not isinstance(entry, dict):
            continue
        t = entry.get("type")
        if t == role_type:
            return entry
        if t == ROLE_TYPE_ALL and wildcard is None:
            wildcard = entry
    return wildcard


def _is_allowed(type_entry: dict | None) -> bool:
    if type_entry is None:
        return False
    return bool(type_entry.get("allowed", True))


def _is_mandatory(type_entry: dict | None) -> bool:
    if type_entry is None:
        return False
    return bool(type_entry.get("mandatory", False))


def _entries(type_entry: dict | None) -> list[dict]:
    if type_entry is None:
        return []
    raw = type_entry.get("entries") or []
    return [e for e in raw if isinstance(e, dict)]


def _resolved_types(role_type_filter: str | None) -> tuple[str, ...]:
    if role_type_filter is None:
        return ROLE_TYPES
    if role_type_filter not in ROLE_TYPES:
        raise SystemExit(
            f"--type: unknown role type {role_type_filter!r}; "
            f"valid types: {', '.join(ROLE_TYPES)}"
        )
    return (role_type_filter,)


# === Render: text ===========================================================


def _policy_label(allowed: bool, mandatory: bool) -> str:
    if not allowed:
        return "FORBIDDEN"
    if mandatory:
        return "MUST"
    return "MAY"


def _entry_label(allowed: bool, mandatory: bool, marker: bool) -> str:
    parts = [_policy_label(allowed, mandatory)]
    if marker:
        parts.append("marker")
    return ", ".join(parts)


def _render_files_text(role_type_filter: str | None) -> Iterator[str]:
    types = _resolved_types(role_type_filter)
    for file_path, file_entry in ROLE_FILES.items():
        yield f"📄 {file_path}"
        description = str(file_entry.get("description", "")).strip()
        if description:
            yield f"     {description}"
        for role_type in types:
            type_entry = _entries_for_type(file_entry, role_type)
            allowed = _is_allowed(type_entry)
            mandatory = _is_mandatory(type_entry)
            label = _policy_label(allowed, mandatory)
            yield f"   • {role_type:<16} {label}"
            for sub in _entries(type_entry):
                path = sub.get("path", "?")
                sub_label = _entry_label(
                    bool(sub.get("allowed", True)),
                    bool(sub.get("mandatory", False)),
                    bool(sub.get("marker", False)),
                )
                yield f"       └─ {path}  ({sub_label})"
        yield ""


def _render_types_text(role_type_filter: str | None) -> Iterator[str]:
    types = _resolved_types(role_type_filter)
    for role_type in types:
        yield f"🧩 {role_type}"
        for file_path, file_entry in ROLE_FILES.items():
            type_entry = _entries_for_type(file_entry, role_type)
            allowed = _is_allowed(type_entry)
            mandatory = _is_mandatory(type_entry)
            if not allowed:
                continue
            label = _policy_label(allowed, mandatory)
            yield f"   • {file_path:<32} {label}"
            for sub in _entries(type_entry):
                path = sub.get("path", "?")
                sub_label = _entry_label(
                    bool(sub.get("allowed", True)),
                    bool(sub.get("mandatory", False)),
                    bool(sub.get("marker", False)),
                )
                yield f"       └─ {path}  ({sub_label})"
        yield ""


def _render_markers_text(role_type_filter: str | None) -> Iterator[str]:
    types = _resolved_types(role_type_filter)
    yield "🎯 Type markers (file.path that decides each role type)"
    yield ""
    any_marker = False
    for role_type in types:
        listed = False
        for file_path, file_entry in ROLE_FILES.items():
            type_entry = _entries_for_type(file_entry, role_type)
            for sub in _entries(type_entry):
                if not bool(sub.get("marker", False)):
                    continue
                if not listed:
                    yield f"   {role_type}"
                    listed = True
                any_marker = True
                yield f"       └─ {file_path}  →  {sub.get('path', '?')}"
        if listed:
            yield ""
    if not any_marker:
        yield "   (no markers declared for the selected type)"


# === Render: json ===========================================================


def _files_json(role_type_filter: str | None) -> dict:
    types = _resolved_types(role_type_filter)
    out: dict[str, dict] = {}
    for file_path, file_entry in ROLE_FILES.items():
        per_type: dict[str, dict] = {}
        for role_type in types:
            type_entry = _entries_for_type(file_entry, role_type)
            per_type[role_type] = {
                "allowed": _is_allowed(type_entry),
                "mandatory": _is_mandatory(type_entry),
                "entries": [
                    {
                        "path": str(sub.get("path", "")),
                        "allowed": bool(sub.get("allowed", True)),
                        "mandatory": bool(sub.get("mandatory", False)),
                        "marker": bool(sub.get("marker", False)),
                    }
                    for sub in _entries(type_entry)
                ],
            }
        out[file_path] = {
            "description": str(file_entry.get("description", "")),
            "types": per_type,
        }
    return out


def _types_json(role_type_filter: str | None) -> dict:
    types = _resolved_types(role_type_filter)
    out: dict[str, dict] = {}
    for role_type in types:
        files: dict[str, dict] = {}
        for file_path, file_entry in ROLE_FILES.items():
            type_entry = _entries_for_type(file_entry, role_type)
            allowed = _is_allowed(type_entry)
            if not allowed:
                continue
            files[file_path] = {
                "allowed": allowed,
                "mandatory": _is_mandatory(type_entry),
                "entries": [
                    {
                        "path": str(sub.get("path", "")),
                        "allowed": bool(sub.get("allowed", True)),
                        "mandatory": bool(sub.get("mandatory", False)),
                        "marker": bool(sub.get("marker", False)),
                    }
                    for sub in _entries(type_entry)
                ],
            }
        out[role_type] = files
    return out


def _markers_json(role_type_filter: str | None) -> dict:
    types = _resolved_types(role_type_filter)
    out: dict[str, list[dict]] = {}
    for role_type in types:
        markers: list[dict] = []
        for file_path, file_entry in ROLE_FILES.items():
            type_entry = _entries_for_type(file_entry, role_type)
            for sub in _entries(type_entry):
                if not bool(sub.get("marker", False)):
                    continue
                markers.append(
                    {
                        "file": file_path,
                        "path": str(sub.get("path", "")),
                    }
                )
        out[role_type] = markers
    return out


# === Argparse plumbing ======================================================


def _print_lines(lines: Iterable[str]) -> None:
    for line in lines:
        print(line)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--type",
        dest="role_type",
        default=None,
        choices=ROLE_TYPES,
        help="Limit output to a single role type (default: every type).",
    )
    parser.add_argument(
        "--format",
        choices=_FORMATS,
        default="text",
        help="Output format (default: text).",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cli.meta.roles.mapping",
        description=("Inspect the role-file mapping SPOT (utils/roles/mapping.py)."),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    files_parser = sub.add_parser(
        "files",
        help="List every role file with its per-type policy.",
    )
    _add_common_args(files_parser)

    types_parser = sub.add_parser(
        "types",
        help="List every role type with the files it MAY / MUST ship.",
    )
    _add_common_args(types_parser)

    markers_parser = sub.add_parser(
        "markers",
        help="List the type markers that decide each role type.",
    )
    _add_common_args(markers_parser)

    args = parser.parse_args(argv)

    if args.format == "json":
        if args.command == "files":
            payload = _files_json(args.role_type)
        elif args.command == "types":
            payload = _types_json(args.role_type)
        elif args.command == "markers":
            payload = _markers_json(args.role_type)
        else:  # pragma: no cover - argparse already enforces required
            parser.error(f"unknown command {args.command!r}")
            return 2
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    # text
    if args.command == "files":
        _print_lines(_render_files_text(args.role_type))
    elif args.command == "types":
        _print_lines(_render_types_text(args.role_type))
    elif args.command == "markers":
        _print_lines(_render_markers_text(args.role_type))
    else:  # pragma: no cover
        parser.error(f"unknown command {args.command!r}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
