"""Flag any literal ``condition: service_*`` line in ``*compose.yml.j2``
templates.

The canonical, swarm-compatible way to declare service dependencies in
this codebase is the ``depends_on`` lookup:

    {{ lookup('depends_on', {<svc>: 'service_healthy', …}) }}

The lookup emits the map form for compose (with conditions) and the
list form for swarm. Hand-writing the per-mode gate
(``{% if DEPLOYMENT_MODE == 'swarm' %} … {% else %} … {% endif %}``)
is the pattern this rule eliminates - it is repetitive, easy to
forget, and the lookup is the single source of truth for the
compose/swarm dependency shape.

Per-line opt-out: ``# nocheck: compose-depends-on-must-use-lookup`` on
the offending line or the immediately preceding non-empty line. Use it
ONLY when the depends_on shape genuinely cannot route through the
lookup (very rare - if you reach for this, document why).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "compose-depends-on-must-use-lookup"

# A literal YAML `depends_on:` keyword line. The lookup output renders
# this keyword at render time, but the TEMPLATE source never does --
# the source carries the call form `{{ lookup('depends_on', ...) }}`,
# so the keyword token never appears in source for migrated blocks.
_DEPENDS_ON_KEY = re.compile(r"^\s*depends_on\s*:\s*(?:#.*)?$")

# `depends_on: [a, b]` flow form on a single line.
_DEPENDS_ON_FLOW = re.compile(r"^\s*depends_on\s*:\s*\[")

# A literal map-form `condition: service_*` line -- the swarm-incompatible
# form the lookup also eliminates.
_CONDITION = re.compile(
    r"^\s*condition:\s*service_(?:started|healthy|completed_successfully)\b"
)


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if "/templates/" not in rel_path:
        return False
    name = Path(rel_path).name
    # Match every compose-related Jinja YAML template:
    # - `compose.yml.j2`
    # - `bootstrap.compose.yml.j2`, `worker.compose.yml.j2`, …
    # - `compose.override.yml.j2`
    # - `compose-inits.yml.j2`
    # The `lookup('depends_on', …)` contract applies to any file that
    # docker compose / docker stack deploy reads, not only the
    # canonical top-level one.
    return name.endswith(".yml.j2") and "compose" in name


class TestComposeTemplateUsesDependsOnLookup(unittest.TestCase):
    def test_no_raw_depends_on_in_compose_template(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not (
                    _DEPENDS_ON_KEY.match(line)
                    or _DEPENDS_ON_FLOW.match(line)
                    or _CONDITION.match(line)
                ):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found raw `depends_on:` blocks (either the YAML keyword "
                "line, the flow-form `depends_on: [a, b]`, or a literal "
                "`condition: service_*` line) in `*compose.yml.j2` "
                "templates. The canonical pattern is the `depends_on` "
                "lookup, which emits the keyword AND the body in the "
                "correct shape for compose and swarm:\n\n"
                "    {{ lookup('depends_on', {SVC: 'service_healthy', …}) }}\n"
                "    {{ lookup('depends_on', [SVC_A, SVC_B]) }}   # default condition\n\n"
                "Mapping accepts `None` to use the default condition\n"
                "(`service_started`); plain list of names also works\n"
                "and treats all entries with the default. The `indent`\n"
                "kwarg controls the leading-spaces of the `depends_on:`\n"
                "line.\n\n"
                "The app-aware `lookup('container_depends_on', application_id)`\n"
                "is a separate, allowed escape hatch -- it derives DB / redis\n"
                "dependencies from the application config and emits its own\n"
                "block. Calls to that lookup are not flagged because the call\n"
                "form does not contain a literal `depends_on:` token in the\n"
                "template source.\n\n"
                "Mark with `# nocheck: compose-depends-on-must-use-lookup` "
                "only when the depends_on shape genuinely cannot route "
                "through the lookup.\n\n"
                f"Offending lines:\n{formatted}"
            )

    def test_container_depends_on_calls_use_indent_filter(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            lines = content.splitlines()
            idx, total = 0, len(lines)
            while idx < total:
                opener = lines[idx]
                if "lookup('container_depends_on'" not in opener:
                    idx += 1
                    continue
                start = idx
                call = opener
                while "}}" not in call and idx + 1 < total:
                    idx += 1
                    call += "\n" + lines[idx]
                at_col0 = opener.startswith("{{")
                missing_filter = "| indent(" not in call
                if at_col0 or missing_filter:
                    reasons = []
                    if at_col0:
                        reasons.append(
                            "starts at column 0 (indent to the service body)"
                        )
                    if missing_filter:
                        reasons.append("missing | indent(4)")
                    findings.append((rel, start + 1, "; ".join(reasons)))
                idx += 1

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "The `container_depends_on` lookup emits its block at column 0 "
                "(like `container_networks`), so every call must sit at the "
                "service-body indent and pipe through `| indent(4)`:\n\n"
                "    {{ lookup('container_depends_on', application_id) | indent(4) }}\n\n"
                "A call at column 0, or without the filter, renders the "
                "`depends_on:` block at the wrong indentation.\n\n"
                f"Offending calls:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
