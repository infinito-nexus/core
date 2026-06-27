# tests/integration/test_compose_templates_require_image_for_build.py
#
# Integration test:
# Ensures that every sys-svc-compose template/file that contains a `build:` mapping
# also contains an `image:` key on the same indentation level (same YAML mapping level).
#
# Checked files:
#   - roles/*/templates/compose.yml.j2
#   - roles/*/files/compose.yml
#
# Rationale:
# Your CA-injection logic (and other tooling) may need a stable image name to inspect
# entrypoint/cmd. Compose allows build without image, but then image names are not stable.

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

BUILD_RE = re.compile(r"^(?P<indent>[ \t]*)build:\s*(#.*)?$")
IMAGE_RE = re.compile(r"^(?P<indent>[ \t]*)image:\s*(?P<rest>.+)?$")
CONTAINER_IMAGE_LOOKUP_RE = re.compile(
    r"^(?P<indent>[ \t]*)\{\{\s*lookup\(\s*['\"]container_image['\"]\s*,"
)
COMMENTED_RE = re.compile(r"^\s*#")
BLANK_RE = re.compile(r"^\s*$")


@dataclass
class Finding:
    file: str
    build_line: int
    build_indent: int
    note: str


def _is_ignored_line(line: str) -> bool:
    return bool(BLANK_RE.match(line) or COMMENTED_RE.match(line))


def _indent_len(indent: str) -> int:
    # Tabs are allowed in regex, but we treat them as 1 unit here.
    # If you enforce spaces-only, this still works.
    return len(indent.replace("\t", " "))


def _block_bounds_for_key(
    lines: list[str], idx: int, key_indent_len: int
) -> tuple[int, int]:
    """
    Determine bounds of the YAML mapping block that contains the key at lines[idx],
    based on indentation dropping below key_indent_len.
    Returns (start_inclusive, end_exclusive).
    """
    # Scan upwards to find where indentation drops below key_indent_len.
    start = idx
    j = idx - 1
    while j >= 0:
        ln = lines[j]
        if _is_ignored_line(ln):
            j -= 1
            continue

        # Indentation of this non-empty, non-comment line
        cur_indent = len(ln) - len(ln.lstrip(" \t"))
        cur_indent_len = _indent_len(ln[:cur_indent])

        if cur_indent_len < key_indent_len:
            break
        start = j
        j -= 1

    # Scan downwards similarly
    end = idx + 1
    k = idx + 1
    while k < len(lines):
        ln = lines[k]
        if _is_ignored_line(ln):
            k += 1
            end = k
            continue

        cur_indent = len(ln) - len(ln.lstrip(" \t"))
        cur_indent_len = _indent_len(ln[:cur_indent])

        if cur_indent_len < key_indent_len:
            break
        k += 1
        end = k

    return start, end


def _has_image_same_indent(
    lines: list[str], start: int, end: int, indent_str: str
) -> bool:
    needle = f"{indent_str}image:"
    container_image_lookup_needle = f"{indent_str}{{{{"
    for i in range(start, end):
        ln = lines[i]
        if _is_ignored_line(ln):
            continue
        if ln.startswith(needle):
            return True
        if ln.startswith(
            container_image_lookup_needle
        ) and CONTAINER_IMAGE_LOOKUP_RE.match(ln):
            return True
    return False


def _scan_file_for_missing_image(path: Path) -> list[Finding]:
    try:
        text = read_text(str(path))
    except UnicodeDecodeError:
        return []
    lines = text.splitlines()

    findings: list[Finding] = []

    for idx, ln in enumerate(lines):
        if _is_ignored_line(ln):
            continue

        m = BUILD_RE.match(ln)
        if not m:
            continue

        indent_str = m.group("indent") or ""
        indent_len = _indent_len(indent_str)

        # Determine block bounds for this build: key
        b_start, b_end = _block_bounds_for_key(lines, idx, indent_len)

        # Need image: at same indent level somewhere within that block
        if not _has_image_same_indent(lines, b_start, b_end, indent_str):
            findings.append(
                Finding(
                    file=str(path),
                    build_line=idx + 1,  # 1-based for humans
                    build_indent=indent_len,
                    note="Found `build:` without `image:` at the same indentation level in the same mapping block.",
                )
            )

    return findings


class TestComposeBuildRequiresImage(unittest.TestCase):
    def test_all_compose_templates_and_files_have_image_for_build(self) -> None:
        roles_dir = PROJECT_ROOT / "roles"

        patterns = [
            f"*/{ROLE_FILE_TEMPL_COMPOSE}",
            "*/files/compose.yml",
        ]

        targets: list[Path] = []
        for pat in patterns:
            targets.extend(sorted(roles_dir.glob(pat)))

        self.assertTrue(
            targets,
            f"No compose templates/files found under {roles_dir} for patterns: {patterns}",
        )

        all_findings: list[Finding] = []
        for f in targets:
            all_findings.extend(_scan_file_for_missing_image(f))

        if all_findings:
            # Pretty error output
            msg_lines = [
                "Some sys-svc-compose templates/files contain a `build:` key but are missing an `image:` key "
                "at the same indentation level (same YAML mapping level).",
                "",
                "Offenders:",
            ]
            msg_lines.extend(
                f"- {it.file}:{it.build_line} (build indent={it.build_indent}) -> {it.note}"
                for it in all_findings
            )
            msg_lines.append("")
            msg_lines.append(
                "Fix: for each service that has `build:`, add a stable `image:` name on the same level, e.g."
            )
            msg_lines.append("  service:")
            msg_lines.append("    image: myorg/myimage:local")
            msg_lines.append("    build:")
            msg_lines.append("      context: .")
            self.fail("\n".join(msg_lines))


if __name__ == "__main__":
    unittest.main()
