from __future__ import annotations

import re
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT
from .test_no_jinja_default_on_spot_path import (
    _DEFAULT_FILTER_RE,
    _JINJA_BLOCK_RE,
    _LEADING_PATH_RE,
    _RAW_BLOCK_RE,
    _find_default_target,
)

# Ansible "magic" / connection variables that are always defined for
# every task in every play. A Jinja ``| default(...)`` on any of them
# is dead code: the filter never fires, and the value behind it
# silently masks the real one if the upstream contract ever changes.
#
# Scope is intentionally conservative: only the bare name (no dotted
# access) is checked. ``groups.foo``, ``hostvars.<host>.<var>``,
# ``ansible_facts.<x>`` etc. may legitimately be absent, so defaults
# on dotted accesses are NOT flagged.
ANSIBLE_MAGIC_VARS = frozenset(
    {
        "group_names",
        "groups",
        "hostvars",
        "inventory_hostname",
        "inventory_hostname_short",
        "inventory_dir",
        "inventory_file",
        "playbook_dir",
        "play_hosts",
        "ansible_play_hosts",
        "ansible_play_hosts_all",
        "ansible_play_batch",
        "ansible_play_name",
        "ansible_check_mode",
        "ansible_diff_mode",
        "ansible_verbosity",
        "ansible_version",
        "ansible_run_tags",
        "ansible_skip_tags",
        "ansible_forks",
        "ansible_limit",
        "ansible_search_path",
        "ansible_inventory_sources",
        "ansible_config_file",
        "ansible_playbook_python",
        "omit",
    }
)

SCAN_DIRS = ("roles", "tasks", "group_vars")
SCAN_SUFFIXES = (".yml", ".yaml", ".j2")
_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*ansible-magic-default")


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    var: str
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: '{self.var}' -> {self.snippet}"


def _iter_target_files() -> list[Path]:
    scan_prefix = tuple(str(PROJECT_ROOT / d) + "/" for d in SCAN_DIRS)
    return [
        Path(abs_path)
        for abs_path in iter_project_files(extensions=SCAN_SUFFIXES, exclude_tests=True)
        if abs_path.startswith(scan_prefix)
    ]


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    def _mask(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    masked = _RAW_BLOCK_RE.sub(_mask, text)
    text_lines = text.splitlines()

    line_starts: list[int] = [0]
    for i, ch in enumerate(masked):
        if ch == "\n":
            line_starts.append(i + 1)

    def _line_of(offset: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    for block in _JINJA_BLOCK_RE.finditer(masked):
        expr = block.group(1)
        block_offset = block.start(1)
        for m_default in _DEFAULT_FILTER_RE.finditer(expr):
            target = _find_default_target(expr, m_default.start())
            if target is None:
                continue
            if target.startswith("(") and target.endswith(")"):
                target = target[1:-1].strip()

            m_path = _LEADING_PATH_RE.match(target)
            if not m_path:
                continue
            if target[m_path.end() :].strip():
                continue

            dotted = m_path.group(1)
            if "." in dotted:
                continue
            if dotted not in ANSIBLE_MAGIC_VARS:
                continue

            line_no = _line_of(block_offset + m_default.start())
            snippet_line = (
                text_lines[line_no - 1].strip() if line_no - 1 < len(text_lines) else ""
            )
            if _NOCHECK_RE.search(snippet_line):
                continue

            findings.append(
                Finding(file=path, line=line_no, var=dotted, snippet=snippet_line)
            )

    return findings


class TestNoJinjaDefaultOnAnsibleMagicVar(unittest.TestCase):
    """Forbid ``| default(...)`` on Ansible magic / connection variables
    that are always defined per task (``group_names``,
    ``inventory_hostname``, ``groups``, ``hostvars``, …).

    Only the bare variable form is checked. Dotted accesses like
    ``groups.foo`` or ``hostvars.<host>.<var>`` may legitimately be
    absent and are not flagged.

    Suppress a single line with ``# nocheck: ansible-magic-default``
    plus a one-line rationale.
    """

    def test_no_default_on_ansible_magic_var(self) -> None:
        findings: list[Finding] = []
        for path in _iter_target_files():
            findings.extend(_scan_file(path))

        if findings:
            formatted = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(
                "Found `| default(...)` on Ansible magic variables that "
                "are always defined per task. Drop the default, or "
                "annotate the line with `# nocheck: ansible-magic-default` "
                "and a one-line rationale.\n"
                f"{formatted}"
            )


class TestAnsibleMagicDefaultScannerFixtures(unittest.TestCase):
    """Positive-case fixtures for `_scan_file`. Guards against silent
    regressions where helper imports or regex changes would let the
    repo-scan loop produce 0 findings even when the rule is broken.
    """

    def _scan(self, content: str) -> list[Finding]:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fixture.yml"
            p.write_text(content)
            return _scan_file(p)

    def test_flags_group_names_default(self) -> None:
        findings = self._scan('foo: "{{ group_names | default([]) | length }}"\n')
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].var, "group_names")

    def test_flags_inventory_hostname_default(self) -> None:
        findings = self._scan("foo: \"{{ inventory_hostname | default('x') }}\"\n")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].var, "inventory_hostname")

    def test_skips_dotted_access(self) -> None:
        # `groups.foo` may legitimately be absent — defaults are allowed.
        findings = self._scan('foo: "{{ groups.foo | default([]) }}"\n')
        self.assertEqual(findings, [])

    def test_skips_non_magic_var(self) -> None:
        findings = self._scan('foo: "{{ my_app_var | default([]) }}"\n')
        self.assertEqual(findings, [])

    def test_respects_nocheck_suppression(self) -> None:
        findings = self._scan(
            'foo: "{{ group_names | default([]) }}"  # nocheck: ansible-magic-default\n'
        )
        self.assertEqual(findings, [])

    def test_skips_raw_block(self) -> None:
        # `{% raw %}...{% endraw %}` is documentation, not live Jinja.
        findings = self._scan(
            "foo: |\n  {% raw %}{{ group_names | default([]) }}{% endraw %}\n"
        )
        self.assertEqual(findings, [])

    def test_reports_correct_line_number(self) -> None:
        findings = self._scan(
            "key1: 'a'\nkey2: \"{{ group_names | default([]) }}\"\nkey3: 'c'\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line, 2)


if __name__ == "__main__":
    unittest.main()
