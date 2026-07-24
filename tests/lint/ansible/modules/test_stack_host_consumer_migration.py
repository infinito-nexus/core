"""Lint: tasks reading a stack_host_template: destination must carry an IS_STACK_HOST gate or `# nocheck: stack-host-consumer`."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

PRODUCER_PATTERN = re.compile(
    r"^(?P<indent>\s*)-?\s*stack_host_template\s*:\s*(?:#.*)?$"
)
DEST_LINE_PATTERN = re.compile(r"^(?P<indent>\s*)dest\s*:\s*(?P<value>.*?)\s*$")

UPPER_NAME = re.compile(r"\b([A-Z][A-Z0-9_]{4,})\b")
PATH_NAME_HINTS = ("PATH", "DIR", "FILE", "HOST_", "_HOST", "_ABS", "_DEST", "_SRC")
LOOKUP_TUPLE = re.compile(
    r"lookup\(\s*['\"](?P<kind>[a-z0-9_-]+)['\"]\s*,\s*[^,)]+?,\s*['\"](?P<path>[a-z0-9_.-]+)['\"]"
)

CONSUMER_MODULES = frozenset(
    {
        "copy",
        "assemble",
        "lineinfile",
        "blockinfile",
        "replace",
        "slurp",
        "find",
        "command",
        "shell",
        "script",
        "include_vars",
        "unarchive",
        "fetch",
        "template",
    }
)
MODULE_LINE = re.compile(
    r"^(?P<indent>\s*)-?\s*(?:ansible\.builtin\.)?(?P<module>[a-z_]+)\s*:\s*(?:#.*)?$"
)
PATH_ARG_KEYS = ("path", "dest", "src", "cmd", "argv", "file", "name")
GATE_RE = re.compile(r"\b(?:IS_STACK_HOST|MODE_ASSERT_LOCAL)\s*\|\s*bool\b")
DELEGATE_RE = re.compile(r"delegate_to\s*:\s*[\"']?\{\{\s*STACK_HOST\s*\}\}")
NOCHECK_MARKER = "nocheck: stack-host-consumer"


def _find_task_block_end(lines: list[str], start_idx: int, base_indent: int) -> int:
    end = start_idx + 1
    while end < len(lines):
        line = lines[end]
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            indent = len(line) - len(stripped)
            if indent <= base_indent:
                break
        end += 1
    return end


def _multi_line_value(lines: list[str], start_idx: int, indent: int) -> str:
    end = start_idx + 1
    while end < len(lines):
        line = lines[end]
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            cur_indent = len(line) - len(stripped)
            if cur_indent <= indent:
                break
        end += 1
    return " ".join(line.strip() for line in lines[start_idx:end])


def _harvest_identifiers(value: str) -> set[str]:
    keys: set[str] = set()
    for name in UPPER_NAME.findall(value):
        if any(hint in name for hint in PATH_NAME_HINTS):
            keys.add(name)
    for kind, path in LOOKUP_TUPLE.findall(value):
        keys.add(f"lookup:{kind}:{path}")
    return keys


def _is_gated(block_lines: list[str]) -> bool:
    body = "\n".join(block_lines)
    if NOCHECK_MARKER in body:
        return True
    if GATE_RE.search(body):
        return True
    return bool(DELEGATE_RE.search(body) and "run_once" in body)


def _path_args_concat(block_lines: list[str]) -> str:
    parts: list[str] = []
    for line in block_lines:
        for key in PATH_ARG_KEYS:
            m = re.match(rf"^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", line)
            if m:
                parts.append(m.group(1))
    return " ".join(parts)


class TestStackHostConsumerMigration(unittest.TestCase):
    def test_no_ungated_consumers_of_stack_host_template_destinations(self):
        producer_keys: set[str] = set()
        producer_locations: set[tuple[str, int]] = set()

        scanned_files: list[tuple[str, list[str]]] = []
        for path_str, content in iter_project_files_with_content(extensions=(".yml",)):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if rel.startswith("tests/lint/"):
                continue
            scanned_files.append((rel, content.splitlines()))

        for rel, lines in scanned_files:
            for idx, line in enumerate(lines):
                producer_match = PRODUCER_PATTERN.match(line)
                if not producer_match:
                    continue
                base_indent = len(producer_match.group("indent"))
                block_end = _find_task_block_end(lines, idx, base_indent)
                for inner_idx, inner in enumerate(lines[idx + 1 : block_end]):
                    dest_match = DEST_LINE_PATTERN.match(inner)
                    if not dest_match:
                        continue
                    raw_value = _multi_line_value(
                        lines, idx + 1 + inner_idx, len(dest_match.group("indent"))
                    )
                    producer_keys.update(_harvest_identifiers(raw_value))
                    producer_locations.add((rel, idx + 1))
                    break

        if not producer_keys:
            self.skipTest("No stack_host_template: producers discovered")

        findings: list[tuple[str, int, str, str]] = []
        for rel, lines in scanned_files:
            for idx, line in enumerate(lines):
                module_match = MODULE_LINE.match(line)
                if not module_match:
                    continue
                module = module_match.group("module")
                if module not in CONSUMER_MODULES:
                    continue
                if module == "stack_host_template":
                    continue
                if (rel, idx + 1) in producer_locations:
                    continue
                base_indent = len(module_match.group("indent"))
                block_end = _find_task_block_end(lines, idx, base_indent)
                block_lines = lines[idx:block_end]
                args_concat = _path_args_concat(block_lines)
                matched = next(
                    (key for key in producer_keys if key in args_concat),
                    None,
                )
                if not matched:
                    continue

                if _is_gated(block_lines):
                    continue

                findings.append((rel, idx + 1, module, matched))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no} ({module}): touches `{key}` written by stack_host_template:"
                for path, line_no, module, key in sorted(
                    findings, key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found tasks that touch a stack-host-template destination but are "
                "not IS_STACK_HOST-gated. On workers the file does not exist, so "
                "these tasks will abort.\n\n"
                "Gate the task (or its enclosing block) with "
                "`when: IS_STACK_HOST | bool` or `when: MODE_ASSERT_LOCAL | bool`, "
                f"or suppress with `# {NOCHECK_MARKER} (<reason>)` if the consumer "
                "is structurally safe (parent include already manager-only, file "
                "produced unconditionally elsewhere, ...).\n\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
