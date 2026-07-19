"""Strict guard for ALL compose templates: inline ``volumes:`` /
``configs:`` / ``secrets:`` blocks in ``compose.yml.j2`` are forbidden.
Every mount surface MUST flow through ``lookup('compose_volumes', ...)``
(top-level) and ``lookup('container_volumes', application_id, service)``
(per-service). That makes ``meta/volumes.yml`` the single source for
NFS opt-in, swarm config/secret distribution, and reschedule-safe
bind sources.

Per-line opt-out: ``# nocheck: compose-inline-mount-section`` on the
offending line or the immediately preceding non-empty line. Reserved
for the few legitimate exceptions where the mount cannot be expressed
in meta (docker socket, loop-driven per-item mounts, runtime-rotated
files).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "compose-inline-mount-section"

_COMPOSE_TEMPLATE_BASENAME = re.compile(r"^compose(?:[.\-][^/]+)?\.yml\.j2$")
_INLINE_SECTION = re.compile(r"^(?P<indent>\s*)(volumes|configs|secrets):\s*$")
_LOOKUP_CALL = re.compile(r"lookup\(\s*['\"](compose_volumes|container_volumes)['\"]")

# A short-form bind entry parses as `- "<src>:<dst>[:ro]"`. We capture
# (src, dst) and only flag when dst names a single file (see
# _IS_SINGLE_FILE_TARGET). Directory binds and named volumes are
# tolerated inline.
_SHORT_FORM_BIND = re.compile(
    r"""
    ^\s*-\s*
    ["']?
    (?P<src>(?:\{\{[^}]*\}\}|[^:"'\s])+?)
    :
    (?P<dst>(?:\{\{[^}]*\}\}|[^:"'\s])+?)
    (?::ro\b|:rw\b)?
    """,
    re.VERBOSE,
)
_FILE_EXT_PATH = re.compile(
    r"\.(?:yaml|yml|json|conf|cfg|ini|toml|lua|php|exs|env|sh|crt|key|pem|html|txt|xml|properties)$"
)
_DIRECTORY_SUFFIX_D = re.compile(r"\.d/?$")
_JINJA_VAR_ONLY = re.compile(r"^\s*\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}\s*$")
_FILE_LIKE_VAR_SUFFIX = re.compile(
    r"_(?:FILE|CONF|YAML|YML|JSON|CFG|INI|TOML|LUA|PHP|EXS|CRT|KEY|PEM|HTML|XML)(?:_|$)"
)


def _is_single_file_target(dst: str) -> bool:
    dst = dst.strip()
    if not dst or dst.endswith("/"):
        return False
    if _DIRECTORY_SUFFIX_D.search(dst):
        return False
    if _FILE_EXT_PATH.search(dst):
        return True
    var_match = _JINJA_VAR_ONLY.match(dst)
    return bool(var_match and _FILE_LIKE_VAR_SUFFIX.search(var_match.group(1)))


# nocheck: project-root-import  literal compose-yml path prefix, not a sys.path walk
_RELATIVE_PREFIXES = ("/", "./", "..")


def _is_host_path_source(src: str) -> bool:
    src = src.strip()
    if src.startswith(_RELATIVE_PREFIXES):
        return True
    return bool(
        re.search(
            r"\{\{[^}]*(?:lookup\(|directories|path_join|HOST|FILE|CONF|PATH|DEST)", src
        )
    )


def _is_compose_template(rel_path: str) -> bool:
    if not (rel_path.startswith("roles/") and "/templates/" in rel_path):
        return False
    return bool(_COMPOSE_TEMPLATE_BASENAME.match(Path(rel_path).name))


def _line_is_lookup_output(line: str) -> bool:
    """Allow inline section keys that are part of the lookup-output line."""
    return bool(_LOOKUP_CALL.search(line))


def _block_contains_single_file_bind(
    lines: list[str], header_idx: int, header_indent: int
) -> bool:
    """Walk the YAML block below the section header (indented strictly
    deeper than the header). True iff any list-item is a single-file
    bind mount (host-path source + file-shaped target). Stops on a
    line with indent <= header (end of block) or EOF.
    """
    for j in range(header_idx + 1, len(lines)):
        raw = lines[j]
        if not raw.strip():
            continue
        leading = len(raw) - len(raw.lstrip())
        if leading <= header_indent:
            return False
        match = _SHORT_FORM_BIND.match(raw)
        if not match:
            continue
        src = match.group("src")
        dst = match.group("dst")
        if not _is_host_path_source(src):
            continue
        if _is_single_file_target(dst):
            return True
    return False


class TestComposeTemplateNoInlineMountSection(unittest.TestCase):
    def test_no_compose_template_has_inline_mount_sections(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_compose_template(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                match = _INLINE_SECTION.match(line)
                if not match:
                    continue
                if _line_is_lookup_output(line):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.rstrip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found inline `volumes:`/`configs:`/`secrets:` sections in "
                "compose.yml.j2. Every mount surface must come from the "
                "plugin output:\n\n"
                "    services:\n"
                "      <svc>:\n"
                "        {{ lookup('container_volumes', application_id, '<svc>') | indent(8) }}\n\n"
                "    {{ lookup('compose_volumes', application_id) }}\n\n"
                "Mark with `# nocheck: compose-inline-mount-section` only "
                "for legitimate exceptions (extra_* injection helpers).\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
