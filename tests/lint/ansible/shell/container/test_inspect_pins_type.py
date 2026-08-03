"""Enforce that every untyped ``container inspect`` / ``docker inspect``
call pins ``--type container``.

Rationale
=========
``docker inspect`` without ``--type`` searches every object kind and
returns the first match. This repository names a role's overlay network
after the role entity (``sys-svc-compose/tasks/utils/network/create.yml``
uses ``network_role_id | get_entity_name``), which for a role whose main
service carries the entity name is byte-identical to its container name.

An untyped inspect can therefore resolve the *network* and report

    template parsing error: map has no entry for key "State"

instead of naming the missing container. That is what took down every
swarm job of run 30709070050: the probe never observed OpenResty's
state, it inspected the ``openresty`` network.

Pinning ``--type container`` cannot make a wrong target right -- that is
``container-exec-resolver``'s job -- but it turns a misleading template
error into ``No such object``, which says what actually happened.

Scope
=====
Only the untyped form is a finding. Typed subcommands
(``container volume inspect``, ``container image inspect``,
``container service inspect``) address non-containers deliberately and
never match.

``roles/`` only. The collision this rule prevents follows from the
role-entity naming convention, so it exists exactly where that
convention does. ``scripts/tests/deploy/`` inspects act nodes in the
outer docker namespace, which carries no role-named overlay networks;
pinning the type there would be churn without a mechanism behind it.

Per-line opt-out
================
Add ``# nocheck: container-inspect-type`` on the same line as the call
or on the immediately preceding non-empty line. For ``argv:`` lists, put
the marker on the ``inspect`` item.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "container-inspect-type"

_INSPECT_CALL = re.compile(r"\b(?:container|docker)\s+inspect\b")

_TYPE_FLAG = re.compile(r"--type[=\s]")

_ARGV_BINARIES = frozenset({"container", "docker"})

_SCANNED_SUFFIXES = (".yml", ".yaml", ".j2", ".sh", ".py")


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    return rel_path.endswith(_SCANNED_SUFFIXES)


def _segments(text: str) -> list[str]:
    """Split *text* at each inspect call, returning the tail of every
    call up to the next one. A tail carries the flags belonging to that
    call and nothing from its neighbours."""
    starts = [match.end() for match in _INSPECT_CALL.finditer(text)]
    if not starts:
        return []
    bounds = [*starts[1:], len(text)]
    return [text[start:end] for start, end in zip(starts, bounds, strict=True)]


def _logical_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Join backslash-continued physical lines into logical ones,
    anchored at the line number where each logical line starts."""
    joined: list[tuple[int, str]] = []
    buffer = ""
    anchor = 0
    for idx, line in enumerate(lines, start=1):
        stripped = line.rstrip()
        if not buffer:
            anchor = idx
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        joined.append((anchor, buffer + stripped))
        buffer = ""
    if buffer:
        joined.append((anchor, buffer))
    return joined


def _collect_scalar_nodes(node: yaml.Node, out: list[tuple[int, str]]) -> None:
    """Append ``(line_no, value)`` for every scalar beneath *node*.
    Folded block scalars arrive with their newlines already collapsed,
    so a call split across source lines reads as one string."""
    if isinstance(node, yaml.ScalarNode):
        out.append((node.start_mark.line + 1, node.value))
        return
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _collect_scalar_nodes(item, out)
        return
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            _collect_scalar_nodes(key, out)
            _collect_scalar_nodes(value, out)


def _collect_argv_item_lists(node: yaml.Node, out: list[list[tuple[int, str]]]) -> None:
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _collect_argv_item_lists(item, out)
        return
    if not isinstance(node, yaml.MappingNode):
        return
    for key, value in node.value:
        if (
            isinstance(key, yaml.ScalarNode)
            and key.value == "argv"
            and isinstance(value, yaml.SequenceNode)
        ):
            out.append(
                [
                    (element.start_mark.line + 1, element.value)
                    for element in value.value
                    if isinstance(element, yaml.ScalarNode)
                ]
            )
        else:
            _collect_argv_item_lists(value, out)


def _argv_is_untyped_inspect(items: list[tuple[int, str]]) -> tuple[int, str] | None:
    """Return the ``inspect`` item when *items* spell an untyped
    ``(container|docker) inspect ...``, else None."""
    if len(items) < 2:
        return None
    if items[0][1] not in _ARGV_BINARIES or items[1][1] != "inspect":
        return None
    if any(value.startswith("--type") for _line_no, value in items[2:]):
        return None
    return items[1]


def _scan_yaml(
    rel_path: str,
    content: str,
    lines: list[str],
    findings: list[tuple[str, int, str]],
) -> None:
    try:
        docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        _scan_flat(rel_path, lines, findings)
        return

    scalars: list[tuple[int, str]] = []
    argv_lists: list[list[tuple[int, str]]] = []
    for doc in docs:
        if doc is None:
            continue
        _collect_scalar_nodes(doc, scalars)
        _collect_argv_item_lists(doc, argv_lists)

    for line_no, value in scalars:
        for segment in _segments(value):
            if _TYPE_FLAG.search(segment):
                continue
            if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                continue
            findings.append((rel_path, line_no, lines[line_no - 1].strip()))

    for items in argv_lists:
        target = _argv_is_untyped_inspect(items)
        if target is None:
            continue
        line_no = target[0]
        if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
            continue
        findings.append((rel_path, line_no, lines[line_no - 1].strip()))


def _scan_flat(
    rel_path: str,
    lines: list[str],
    findings: list[tuple[str, int, str]],
) -> None:
    for line_no, text in _logical_lines(lines):
        if text.lstrip().startswith("#"):
            continue
        for segment in _segments(text):
            if _TYPE_FLAG.search(segment):
                continue
            if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                continue
            findings.append((rel_path, line_no, lines[line_no - 1].strip()))


class TestContainerInspectPinsType(unittest.TestCase):
    def test_every_untyped_inspect_pins_container_type(self) -> None:
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(
            extensions=_SCANNED_SUFFIXES,
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue

            lines = content.splitlines()
            if rel.endswith((".yml", ".yaml")):
                _scan_yaml(rel, content, lines, findings)
            else:
                _scan_flat(rel, lines, findings)

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    set(findings), key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found `container inspect` / `docker inspect` calls "
                "without `--type`. Docker then searches every object "
                "kind, and this repository names a role's overlay "
                "network after the same entity as its main container, "
                "so the call can resolve the network and fail with "
                '`map has no entry for key "State"` instead of naming '
                "the missing container.\n\n"
                "Fix: pin the object kind.\n\n"
                "    container inspect --type container -f '...' "
                "{{ X_CONTAINER_ADDRESS }}\n\n"
                "Or, where the target is deliberately not a container, "
                "use the typed subcommand (`container volume inspect`, "
                "`container image inspect`, `container service "
                "inspect`).\n\n"
                "Or add `# nocheck: container-inspect-type` on the same "
                "line or the line immediately above (for `argv:` lists: "
                "on the `inspect` item).\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
