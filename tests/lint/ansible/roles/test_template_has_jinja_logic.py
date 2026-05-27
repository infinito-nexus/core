"""Warn on role templates without Jinja2 substitution (belong under `files/`)."""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.annotations.message import in_github_actions, warning
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

JINJA_RE = re.compile(r"{{|{%|{#")


@dataclass(frozen=True)
class StaticTemplate:
    template_path: Path
    role: str


def _collect_static_templates(root: Path) -> list[StaticTemplate]:
    findings: list[StaticTemplate] = []
    for path, content in iter_project_files_with_content(extensions=(".j2",)):
        rel = Path(path).relative_to(root)
        parts = rel.parts
        if len(parts) < 4 or parts[0] != "roles" or parts[2] != "templates":
            continue
        if JINJA_RE.search(content):
            continue
        findings.append(StaticTemplate(template_path=Path(path), role=parts[1]))
    findings.sort(key=lambda f: (f.role, f.template_path.as_posix()))
    return findings


def _emit_warning(finding: StaticTemplate, root: Path) -> None:
    rel = finding.template_path.relative_to(root).as_posix()
    warning(
        f"{finding.role}: `{rel}` has no Jinja2 substitution; move it to "
        f"`roles/{finding.role}/files/` and reference it via `copy:` / `script:`",
        title="Static .j2 template",
        file=rel,
    )


def _print_summary(findings: list[StaticTemplate], root: Path) -> None:
    if not findings:
        return
    print()
    print(
        f"[WARNING] Role templates without Jinja2 substitution "
        f"(should live under `files/` instead) — {len(findings)}:"
    )
    for f in findings:
        rel = f.template_path.relative_to(root).as_posix()
        print(f"- {rel} ({f.role})")


class TestTemplateHasJinjaLogic(unittest.TestCase):
    def test_role_templates_use_jinja2(self) -> None:
        root = PROJECT_ROOT
        findings = _collect_static_templates(root)

        for finding in findings:
            _emit_warning(finding, root)

        if not in_github_actions():
            _print_summary(findings, root)


if __name__ == "__main__":
    unittest.main()
