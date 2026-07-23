"""Lint: forbid Jinja delimiters inside Ansible conditional keys.

Ansible evaluates ``when`` / ``failed_when`` / ``changed_when`` / ``until``
as bare expressions. Wrapping the value in ``{{ }}`` / ``{% %}`` triggers
the ansible-core deprecation "Conditionals should not be surrounded by
templating delimiters" (removed in 2.23) and, when the templated string
flows into a ``(x | default(true)) | bool`` data conditional, the
"``bool`` filter coerced invalid value (str)" deprecation.

Scope: ``.yml`` / ``.yaml`` under ``roles/*/{tasks,handlers,vars}/``.

Excluded:

* ``roles/*/meta/{volumes,networks,services}.yml`` -- their ``when``
  keys are custom filter fields evaluated by ``render_jinja`` and
  REQUIRE ``{{ }}``; they are never Ansible task conditionals.
* ``.j2`` templates -- not parsed as Ansible conditionals.

Per-item render/apply lists (``role_templates`` for the shared
``sys-svc-compose`` render helper, ``LISTMONK_SETTINGS``) carry their
guard on a ``condition:`` data field, not ``when:``, precisely so a
templated boolean is legal there without colliding with this check.

Suppress a genuine exception with ``# nocheck: templated-conditional``
on the offending line or the line above.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "templated-conditional"
_SCAN_SUFFIXES = (".yml", ".yaml")
_SCAN_SUBDIRS = ("tasks", "handlers", "vars")
_EXCLUDED_META_FILES = frozenset(
    (
        "volumes.yml",
        "networks.yml",
        "services.yml",
    )
)

_CONDITIONAL_KEYS = ("when", "failed_when", "changed_when", "until")
_JINJA = re.compile(r"\{\{|\{%")

_SCALAR_KEY = re.compile(rf"^\s*(?:{'|'.join(_CONDITIONAL_KEYS)}):\s*(?P<value>\S.*)$")
_LIST_KEY = re.compile(rf"^(?P<indent>\s*)(?:{'|'.join(_CONDITIONAL_KEYS)}):\s*$")
_LIST_ITEM = re.compile(r"^(?P<indent>\s*)-\s*(?P<value>.*)$")
_BLOCK_KEY = re.compile(
    rf"^(?P<indent>\s*)(?:{'|'.join(_CONDITIONAL_KEYS)}):\s*[>|][+-]?\d*\s*$"
)


def _candidate_paths() -> list[Path]:
    out: list[Path] = []
    for s in iter_project_files(extensions=_SCAN_SUFFIXES):
        p = Path(s)
        try:
            rel = p.relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) < 3 or parts[0] != "roles":
            continue
        if parts[1] == "meta" and p.name in _EXCLUDED_META_FILES:
            continue
        if not any(sub in parts for sub in _SCAN_SUBDIRS):
            continue
        out.append(p)
    return out


def _hits_for(lines: list[str]) -> list[tuple[int, str]]:
    """Return (1-based line number, snippet) for each templated conditional."""
    hits: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        block_key = _BLOCK_KEY.match(line)
        if block_key:
            key_indent = len(block_key.group("indent"))
            for follow_no in range(idx + 1, len(lines) + 1):
                follow = lines[follow_no - 1]
                if not follow.strip():
                    continue
                if len(follow) - len(follow.lstrip()) <= key_indent:
                    break
                if _JINJA.search(follow):
                    hits.append((idx, line.strip()))
                    break
            continue
        scalar = _SCALAR_KEY.match(line)
        if scalar:
            if _JINJA.search(scalar.group("value")):
                hits.append((idx, line.strip()))
            continue
        list_key = _LIST_KEY.match(line)
        if not list_key:
            continue
        key_indent = len(list_key.group("indent"))
        for follow_no in range(idx + 1, len(lines) + 1):
            follow = lines[follow_no - 1]
            if not follow.strip():
                continue
            item = _LIST_ITEM.match(follow)
            if item is None or len(item.group("indent")) <= key_indent:
                break
            if _JINJA.search(item.group("value")):
                hits.append((follow_no, follow.strip()))
    return hits


class TestNoTemplatedConditionals(unittest.TestCase):
    def test_no_templated_conditionals(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _candidate_paths():
            try:
                text = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if not _JINJA.search(text):
                continue
            lines = text.splitlines()
            file_hits: list[str] = []
            for line_no, snippet in _hits_for(lines):
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                file_hits.append(f"line {line_no}: {snippet}")
            if file_hits:
                offenders[path] = file_hits

        if offenders:
            report = [
                f"{sum(len(v) for v in offenders.values())} templated Ansible "
                "conditional(s) found. Conditionals (when / failed_when / "
                "changed_when / until) must be BARE expressions, never wrapped "
                "in {{ }} or {% %}.",
                "  Fix: drop the delimiters (`when: FLAG | bool`). For per-item "
                "render/apply data guards, use a `condition:` data field (the "
                "sys-svc-compose render helper and LISTMONK_SETTINGS honor it).",
                f"  Suppress a genuine exception with `# nocheck: {_RULE}`.",
            ]
            for path, issues in sorted(offenders.items()):
                report.append(f"  - {path.relative_to(PROJECT_ROOT)}:")
                report.extend(f"      * {i}" for i in issues)
            self.fail("\n".join(report))


if __name__ == "__main__":
    unittest.main()
