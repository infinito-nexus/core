"""Enforce the canonical skeleton of every ``*compose.yml.j2`` template.

The house layout for a compose template is:

    {% include 'roles/sys-svc-compose/templates/base.yml.j2' %}
      {% set service_name = 'nginx' %}
      {% set container_port = 8000 %}
      {{ service_name }}:
        {% include 'roles/sys-svc-container/templates/base.yml.j2' %}
        {{ lookup('container_image', application_id, 'nginx') }}
        ...
        {{ lookup('container_networks') | indent(4) }}

      {% set service_name = 'php' %}
      {{ service_name }}:
        ...

    {{ lookup('compose_volumes', application_id) }}
    {{ lookup('compose_networks') }}

The compose renderer runs with ``lstrip_blocks=True`` (set by the
``stack_host_template`` action plugin for ``compose.yml.j2``), so a block tag's own
leading indentation is stripped at render time WITHOUT eating the preceding newline.
That makes the aligned layout work: ``{% set %}`` at two spaces (the level of the
``{{ service_name }}:`` key) and ``{% include %}`` at four (the service-body level).
A ``{%-`` / ``-%}`` dash still over-trims - it eats the newline and merges lines - and
MUST NOT be used.

The rules this test enforces, distilled from that skeleton:

1. **base-include** - the first line is the shared services header
   ``{% include 'roles/sys-svc-compose/templates/base.yml.j2' %}``.
2. **service-key** - a service is NEVER declared with a literal key
   (``nginx:``) nor a bare variable key (``{{ CHESS_SERVICE }}:``). The
   only accepted form is ``{{ service_name }}:``.
3. **set-service-name** - every ``{{ service_name }}:`` key is preceded by
   its own ``{% set service_name = ... %}`` since the previous service.
4. **vars-before-key** - all per-service knobs (``container_port``,
   ``container_healthcheck``,
   ``container_healthcheck_start_period``, ``docker_restart_policy``,
   ``service_update_order``, ``docker_compose_env``) are set ABOVE the
   ``{{ service_name }}:`` key, never inside the service body.
5. **set-placement** - those ``{% set %}`` lines are indented two spaces (the
   level of the ``{{ service_name }}:`` key) with no ``-`` trim marker.
6. **include-placement** - every ``{% include %}`` inside a service block is
   indented four spaces (the service-body level) with no ``-`` trim marker; the
   shared compose-header include on line 1 stays at column 0, and includes
   wrapped in a ``{% filter %}`` block are exempt.
7. **block-tag-alignment** - a plain ``{% if/elif/else/endif/for/endfor %}`` tag
   is indented to the level of the content it wraps (the shallowest content line
   inside the block). ``lstrip_blocks`` strips the indent, so this is purely for
   readability. Dashed tags, ``{%+`` tags, ``{% filter %}`` / ``{% macro %}``,
   and inline compound tags are left to their author.

Scope: every ``roles/*/templates/*compose.yml.j2`` (the canonical
per-role stack file). ``compose.override.yml.j2`` and
``compose-inits.yml.j2`` fragments are out of scope - they are not
full stacks and do not carry the base header.

Whole-file opt-out: ``{# nocheck: compose-structure #}`` in the first 30
lines, for templates that legitimately deviate (e.g. a
``{% macro %}``-driven file that emits ``{{ name }}:`` from a macro
parameter). Per-line opt-out: ``{# nocheck: compose-structure #}`` on the
offending line or the line above.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at, is_suppressed_in_head
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "compose-structure"

_BASE_INCLUDE = re.compile(
    r"\{%-?\s*include\s+'roles/sys-svc-compose/templates/base\.yml\.j2'\s*-?%\}"
)

_SERVICE_KEY = re.compile(r"^  (?P<key>(?:\{\{.*?\}\}|[A-Za-z0-9_.-])+):[ \t]*$")

_SERVICE_NAME_KEY = re.compile(r"^\{\{\s*service_name\s*\}\}$")
_PURE_INTERP = re.compile(r"^\{\{\s*(?P<inner>.+?)\s*\}\}$")

_SET_LINE = re.compile(
    r"^(?P<indent> *)(?P<open>\{%-?)\s*set\s+(?P<var>\w+)\s*=.*?(?P<close>-?%\})[ \t]*$"
)

_SET_SERVICE_NAME = re.compile(r"\{%-?\s*set\s+service_name\s*=")

_TOP_LEVEL_LOOKUP = re.compile(r"^\s*\{\{\s*lookup\('compose_(?:volumes|networks)'")

_PREAMBLE_CTRL = re.compile(
    r"^\{%-?\s*(?:set|if|elif|else|endif|for|endfor|macro|endmacro|filter|endfilter)\b"
)
_XANCHOR = re.compile(r"^x-[\w-]*\s*:")

_INCLUDE_LINE = re.compile(
    r"^(?P<indent> *)(?P<open>\{%-?)\s*include\b.*?(?P<close>-?%\})[ \t]*$"
)
_FILTER_OPEN = re.compile(r"^\s*\{%-?\s*filter\b")
_FILTER_CLOSE = re.compile(r"^\s*\{%-?\s*endfilter\b")

_BLOCK_OPEN = frozenset({"if", "for", "filter", "macro"})
_BLOCK_MID = frozenset({"elif", "else"})
_BLOCK_CLOSE = frozenset({"endif", "endfor", "endfilter", "endmacro"})
_BLOCK_CTRL = _BLOCK_OPEN | _BLOCK_MID | _BLOCK_CLOSE
# elif/else/endif/for/endfor are the plain guards this rule aligns; filter and
# macro (and any dashed or {%+ tag) are left to their author.
_BLOCK_MODIFIABLE = frozenset({"if", "elif", "else", "endif", "for", "endfor"})
_BLOCK_TAG = re.compile(
    r"^(?P<ind> *)\{%(?P<plus>\+?)(?P<d1>-?)\s*(?P<kw>\w+)\b.*?(?P<d2>-?)%\}[ \t]*$"
)


def _classify_block(line: str) -> tuple[str, str, bool, int] | None:
    """Return ``(keyword, role, is_simple, indent)`` for a whole-line control tag."""
    if line.count("{%") != 1:
        return None
    match = _BLOCK_TAG.match(line)
    if match is None or match.group("kw") not in _BLOCK_CTRL:
        return None
    kw = match.group("kw")
    role = "open" if kw in _BLOCK_OPEN else "close" if kw in _BLOCK_CLOSE else "mid"
    simple = not match.group("plus") and not match.group("d1") and not match.group("d2")
    return kw, role, simple, len(match.group("ind"))


def _block_tag_violations(lines: list[str]) -> list[tuple[int, str]]:
    """Flag simple ``{% if/for/elif/else %}`` tags not aligned with their block."""
    findings: list[tuple[int, str]] = []
    stack: list[dict] = []
    groups: list[dict] = []
    for i, line in enumerate(lines):
        c = _classify_block(line)
        if c is None:
            continue
        _kw, role, _simple, _ind = c
        if role == "open":
            stack.append({"open": i, "mids": []})
        elif role == "mid" and stack:
            stack[-1]["mids"].append(i)
        elif role == "close" and stack:
            g = stack.pop()
            g["close"] = i
            groups.append(g)

    for g in groups:
        inner = [
            len(lines[j]) - len(lines[j].lstrip(" "))
            for j in range(g["open"] + 1, g["close"])
            if lines[j].strip() and _classify_block(lines[j]) is None
        ]
        if not inner:
            continue
        anchor = min(inner)
        for j in [g["open"], g["close"], *g["mids"]]:
            c = _classify_block(lines[j])
            if c and c[2] and c[0] in _BLOCK_MODIFIABLE and c[3] != anchor:
                findings.append(
                    (
                        j + 1,
                        "`{% "
                        + c[0]
                        + " %}` must be indented "
                        + str(anchor)
                        + " spaces to align with the content it wraps (lstrip_blocks "
                        "strips the indent; the tag reads at its block's level)",
                    )
                )
    return findings


_SERVICE_SCOPED_VARS = frozenset(
    {
        "service_name",
        "container_port",
        "container_healthcheck",
        "container_healthcheck_start_period",
        "docker_restart_policy",
        "service_update_order",
        "docker_compose_env",
    }
)


def _is_scan_target(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and "/templates/" in rel_path
        and rel_path.endswith("compose.yml.j2")
    )


def _service_key_message(key: str) -> str | None:
    """Return a fix message for a non-canonical service key, else ``None``."""
    if _SERVICE_NAME_KEY.match(key):
        return None
    if "{{" not in key:
        return (
            "bare literal service key `"
            + key
            + ":` — set `{% set service_name = '"
            + key
            + "' %}` above and declare the service as `{{ service_name }}:`"
        )
    pure = _PURE_INTERP.match(key)
    if pure is not None:
        return (
            "service key `"
            + key
            + ":` must be `{{ service_name }}:` — set `{% set service_name = "
            + pure.group("inner")
            + " %}` above and use `{{ service_name }}:`"
        )
    return (
        "service key `"
        + key
        + ":` must be `{{ service_name }}:` — assign the key to `service_name` "
        "via `{% set service_name = ... %}` above and use `{{ service_name }}:`"
    )


def _base_include_index(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        if _BASE_INCLUDE.search(line):
            return i
    return None


def _rule_a_violation(lines: list[str]) -> tuple[int, str] | None:
    """The base include must be the first meaningful line.

    Only a preamble may precede it: blank lines, ``{# #}`` comments, a ``---``
    document marker, whole-line ``{% set/if/for/... %}`` control tags (including
    their multi-line continuations), and top-level ``x-*:`` anchor blocks.
    """
    i, n = 0, len(lines)
    in_tag = False
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if in_tag:
            if "%}" in stripped or "#}" in stripped:
                in_tag = False
            i += 1
            continue
        if not stripped or stripped == "---":
            i += 1
            continue
        if stripped.startswith("{#"):
            in_tag = "#}" not in stripped
            i += 1
            continue
        if _BASE_INCLUDE.search(line):
            return None
        if _PREAMBLE_CTRL.match(stripped):
            in_tag = "{%" in stripped and "%}" not in stripped
            i += 1
            continue
        if _XANCHOR.match(line):
            i += 1
            while i < n and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                i += 1
            continue
        return (
            i + 1,
            "first meaningful line must be the base include "
            "`{% include 'roles/sys-svc-compose/templates/base.yml.j2' %}` — only "
            "blank lines, `{# #}` comments, `---`, `{% set/if/for %}` preambles, or "
            "`x-*:` anchor blocks may precede it",
        )
    return (
        1,
        "file must include "
        "`{% include 'roles/sys-svc-compose/templates/base.yml.j2' %}`",
    )


def find_structure_violations(lines: list[str]) -> list[tuple[int, str]]:
    """Return ``(line_no, message)`` pairs for every structural deviation."""
    findings: list[tuple[int, str]] = []

    rule_a = _rule_a_violation(lines)
    if rule_a is not None:
        findings.append(rule_a)

    base_idx = _base_include_index(lines)
    region_start = base_idx + 1 if base_idx is not None else 0
    region_end = len(lines)
    for i in range(region_start, len(lines)):
        if _TOP_LEVEL_LOOKUP.match(lines[i]):
            region_end = i
            break

    key_idxs = [
        i for i in range(region_start, region_end) if _SERVICE_KEY.match(lines[i])
    ]

    for k in key_idxs:
        key = _SERVICE_KEY.match(lines[k]).group("key")
        message = _service_key_message(key)
        if message is not None:
            findings.append((k + 1, message))
        prev = max((j for j in key_idxs if j < k), default=-1)
        if not any(_SET_SERVICE_NAME.search(w) for w in lines[prev + 1 : k]):
            findings.append(
                (
                    k + 1,
                    "no `{% set service_name = ... %}` precedes this service key — "
                    "every service sets `service_name` on the line(s) above its key",
                )
            )

    region = range(region_start, region_end)
    boundaries = sorted(
        set(key_idxs)
        | {i for i in region if _SET_SERVICE_NAME.search(lines[i])}
        | {region_end}
    )
    late_idxs: set[int] = set()
    for k in key_idxs:
        nxt = min((b for b in boundaries if b > k), default=region_end)
        for i in range(k + 1, nxt):
            match = _SET_LINE.match(lines[i])
            if match and match.group("var") in _SERVICE_SCOPED_VARS:
                late_idxs.add(i)

    for i in region:
        line = lines[i]
        match = _SET_LINE.match(line)
        if not match or match.group("var") not in _SERVICE_SCOPED_VARS:
            continue
        if i in late_idxs:
            findings.append(
                (
                    i + 1,
                    "`{% set "
                    + match.group("var")
                    + " %}` sits after the `{{ service_name }}:` key — move every "
                    "service variable above the key",
                )
            )
            continue
        has_dash = match.group("open") == "{%-" or match.group("close") == "-%}"
        if len(match.group("indent")) != 2 or has_dash:
            findings.append(
                (
                    i + 1,
                    "`{% set "
                    + match.group("var")
                    + " %}` must be indented two spaces (aligned with the "
                    "`{{ service_name }}:` key) with no `-` trim marker — lstrip_blocks "
                    "strips the indent, a `-` would eat the preceding newline",
                )
            )

    filter_depth = 0
    for i in region:
        line = lines[i]
        if _FILTER_OPEN.match(line):
            filter_depth += 1
            continue
        if _FILTER_CLOSE.match(line):
            filter_depth = max(0, filter_depth - 1)
            continue
        if filter_depth:
            continue
        match = _INCLUDE_LINE.match(line)
        if match is None:
            continue
        has_dash = match.group("open") == "{%-" or match.group("close") == "-%}"
        if len(match.group("indent")) != 4 or has_dash:
            findings.append(
                (
                    i + 1,
                    "`{% include %}` inside a service block must be indented four "
                    "spaces (the service-body level) with no `-` trim marker — "
                    "lstrip_blocks strips the indent so the included body lands right",
                )
            )

    findings.extend(_block_tag_violations(lines))

    return findings


class TestComposeTemplateStructure(unittest.TestCase):
    def test_compose_templates_follow_canonical_structure(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            if is_suppressed_in_head(lines, _RULE):
                continue
            for line_no, message in find_structure_violations(lines):
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, message))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {m}"
                for p, n, m in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                f"{len(findings)} compose-template structure violation(s). Every "
                "`*compose.yml.j2` MUST follow the canonical skeleton: a base-include "
                "header, each service declared as `{{ service_name }}:` with its "
                "`{% set service_name = ... %}` and all per-service `{% set %}` knobs "
                "on column-0, dash-free lines directly above the key, and the "
                "`compose_volumes` / `compose_networks` lookups closing the "
                "file at column 0.\n\n"
                "Opt a template out with `{# nocheck: compose-structure #}` (whole file "
                "in the head, or per line) only when it legitimately deviates.\n\n"
                f"Violations:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
