"""Flag read-only single-file bind mounts in ``compose.yml.j2`` templates
that are swarm-fragile: the source path is rendered on the manager but
the bind only works on whichever node already has that file. When the
task lands on a worker, swarm rejects it with
``bind source path does not exist``.

Recommended fix: migrate the entry to a docker ``configs:`` block so
the manager loads the file at ``stack deploy`` time and swarm
distributes it through raft to every node. Compose-mode honours the
same ``configs:`` block (renders as a bind mount), so the template
stays mode-agnostic. Directory bind mounts and runtime sockets stay as
they are - flag with the per-line opt-out.

Per-line opt-out
================
Add ``# nocheck: bind-mount-single-file-swarm-fragile`` on the same
line as the volume entry, or on the immediately preceding non-empty
line. The opt-out MUST be accompanied by a short comment explaining
WHY this file cannot be a docker config (e.g. socket, rotates at
runtime, multi-MB, the consumer write-backs to it).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "bind-mount-single-file-swarm-fragile"

_IF = re.compile(r"\{%\s*if\s+(?P<expr>.+?)\s*%\}")
_ELIF = re.compile(r"\{%\s*elif\s+(?P<expr>.+?)\s*%\}")
_ELSE = re.compile(r"\{%\s*else\s*%\}")
_ENDIF = re.compile(r"\{%\s*endif\s*%\}")
_COMPOSE_ONLY_GATE = re.compile(
    r"DEPLOYMENT_MODE\s*!=\s*['\"]swarm['\"]"
    r"|DEPLOYMENT_MODE\s*==\s*['\"]compose['\"]"
)
_SWARM_ONLY_GATE = re.compile(
    r"DEPLOYMENT_MODE\s*==\s*['\"]swarm['\"]"
    r"|DEPLOYMENT_MODE\s*!=\s*['\"]compose['\"]"
)

# Short-form volume entry:  - "<src>:<dst>:ro"   or   - <src>:<dst>:ro
# Captures src and dst (Jinja blocks allowed on either side).
_SHORT_FORM_RO = re.compile(
    r"""
    ^\s*-\s*
    ["']?
    (?P<src>(?:\{\{[^}]*\}\}|[^:"'\s])+?)
    :
    (?P<dst>(?:\{\{[^}]*\}\}|[^:"'\s])+?)
    :ro\b
    """,
    re.VERBOSE,
)

# Long-form bind block (multi-line):
#   - type: bind
#     source: ...
#     target: <dst>
#     read_only: true
_LONG_FORM_TYPE_BIND = re.compile(r"^\s*-\s*type:\s*bind\b")
_LONG_FORM_TARGET = re.compile(r"^\s*target:\s*(?P<dst>.+?)\s*$")
_LONG_FORM_SOURCE = re.compile(r"^\s*source:\s*(?P<src>.+?)\s*$")
_LONG_FORM_READ_ONLY_TRUE = re.compile(r"^\s*read_only:\s*true\b")

# Literal-path last segment: must contain a dot, end with a known file
# extension, and NOT end in `.d` (e.g. `conf.d/`, `/etc/systemd/system.d`
# are debian-style additive config directories, not files).
_FILE_LIKE = re.compile(
    r"\.(?:yaml|yml|json|conf|cfg|ini|toml|lua|php|exs|env|sh|crt|key|pem|html|txt|xml|properties)$"
)
_DIRECTORY_SUFFIX_D = re.compile(r"\.d/?$")

# Jinja-only target like `{{ FOO_CONF_FILE }}`: lift the bare var name
# and look for a file-suggesting suffix. Catches dashboard's
# DASHBOARD_CONFIG_YML_DOCKER_DEST etc.
_JINJA_VAR_ONLY = re.compile(r"^\s*\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}\s*$")
_FILE_LIKE_VAR_SUFFIX = re.compile(
    r"_(?:FILE|CONF|YAML|YML|JSON|CFG|INI|TOML|LUA|PHP|EXS|CRT|KEY|PEM|HTML|XML)(?:_|$)"
)

# Special paths that are legitimately bind-mounted as files but cannot
# become docker configs (sockets, kernel interfaces, etc).
_SPECIAL_SOURCES_PREFIX = (
    "/var/run/",
    "/run/",
    "/proc/",
    "/sys/",
    "/dev/",
)


def _is_file_like(dst: str) -> bool:
    dst_trimmed = dst.rstrip()
    if dst_trimmed.endswith("/"):
        return False
    if _DIRECTORY_SUFFIX_D.search(dst_trimmed):
        return False
    if _FILE_LIKE.search(dst_trimmed):
        return True
    # Pure Jinja `{{ VAR }}` target: fall back to variable-name heuristic.
    jinja_var = _JINJA_VAR_ONLY.match(dst_trimmed)
    return bool(jinja_var and _FILE_LIKE_VAR_SUFFIX.search(jinja_var.group(1)))


def _is_special_source(src: str) -> bool:
    src_stripped = src.strip()
    return any(src_stripped.startswith(p) for p in _SPECIAL_SOURCES_PREFIX)


def _is_inside_compose_only_gate(lines: list[str], target_idx: int) -> bool:
    """True iff lines[target_idx] sits under a `DEPLOYMENT_MODE != 'swarm'` gate."""
    stack: list[tuple[str, bool]] = []
    for i, raw in enumerate(lines):
        if i == target_idx:
            return any(_frame_is_compose_only(e, b) for e, b in stack)
        if _IF.search(raw):
            stack.append((_IF.search(raw).group("expr"), False))
        elif _ELIF.search(raw) and stack:
            stack[-1] = (_ELIF.search(raw).group("expr"), False)
        elif _ELSE.search(raw) and stack:
            stack[-1] = (stack[-1][0], True)
        elif _ENDIF.search(raw) and stack:
            stack.pop()
    return False


def _frame_is_compose_only(expr: str, in_else: bool) -> bool:
    if not in_else:
        return bool(_COMPOSE_ONLY_GATE.search(expr))
    return bool(_SWARM_ONLY_GATE.search(expr))


_COMPOSE_TEMPLATE_BASENAME = re.compile(r"^compose(?:[.\-][^/]+)?\.yml\.j2$")


def _is_scan_target(rel_path: str) -> bool:
    if not (rel_path.startswith("roles/") and "/templates/" in rel_path):
        return False
    return bool(_COMPOSE_TEMPLATE_BASENAME.match(Path(rel_path).name))


def _scan_short_form(lines: list[str], rel: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for idx, line in enumerate(lines):
        match = _SHORT_FORM_RO.match(line)
        if not match:
            continue
        src = match.group("src")
        dst = match.group("dst")
        if _is_special_source(src):
            continue
        if not _is_file_like(dst):
            continue
        if _is_inside_compose_only_gate(lines, idx):
            continue
        if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
            continue
        findings.append((rel, idx + 1, line.strip()))
    return findings


def _scan_long_form(lines: list[str], rel: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    i = 0
    while i < len(lines):
        if not _LONG_FORM_TYPE_BIND.match(lines[i]):
            i += 1
            continue
        block_start = i
        target: str | None = None
        source: str | None = None
        is_read_only = False
        # Stop at the next list item / `- type:` or after 6 lines max so
        # the scanner picks up the FIRST target/source/read_only of this
        # block, not values bleeding in from the next one.
        for j in range(block_start + 1, min(block_start + 7, len(lines))):
            if _LONG_FORM_TYPE_BIND.match(lines[j]):
                break
            if re.match(r"^\s*-\s+\S", lines[j]):
                break
            if target is None:
                target_match = _LONG_FORM_TARGET.match(lines[j])
                if target_match:
                    target = target_match.group("dst")
            if source is None:
                source_match = _LONG_FORM_SOURCE.match(lines[j])
                if source_match:
                    source = source_match.group("src")
            if _LONG_FORM_READ_ONLY_TRUE.match(lines[j]):
                is_read_only = True
        i = block_start + 1
        if not (is_read_only and target):
            continue
        if source and _is_special_source(source):
            continue
        if not _is_file_like(target):
            continue
        if _is_inside_compose_only_gate(lines, block_start):
            continue
        if is_suppressed_at(lines, block_start + 1, _RULE, mode="same-or-above"):
            continue
        findings.append(
            (
                rel,
                block_start + 1,
                lines[block_start].strip() + " ... target: " + target,
            )
        )
    return findings


class TestComposeTemplateFileBindMountSwarmFragile(unittest.TestCase):
    def test_no_unguarded_single_file_bind_mounts_in_compose_template(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            findings.extend(_scan_short_form(lines, rel))
            findings.extend(_scan_long_form(lines, rel))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found read-only single-file bind mounts in compose.yml.j2 "
                "templates that are swarm-fragile (the source only exists "
                "on the manager; the task is rejected when scheduled to a "
                "worker).\n\n"
                "Fix: migrate to docker `configs:` so swarm distributes the "
                "file from the manager via raft. Example:\n\n"
                "    services:\n"
                "      dashboard:\n"
                "        configs:\n"
                "          - source: dashboard_config\n"
                "            target: /app/config.yaml\n"
                "            mode: 0440\n\n"
                "    configs:\n"
                "      dashboard_config:\n"
                "        file: ./volumes/config.yaml\n\n"
                "Compose-mode honours the same block (renders as a bind "
                "mount), so the template stays mode-agnostic.\n\n"
                "If the file genuinely cannot be a docker config (socket, "
                "runtime-rotated, multi-MB, the consumer writes back to "
                "it), mark with `# nocheck: bind-mount-single-file-swarm-"
                "fragile` and add a short WHY comment.\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
