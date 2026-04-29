from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from utils.cache.files import read_text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCAN_DIRS = ("roles", "tasks", "playbooks")

_LITERAL_TRUE_RE = re.compile(
    r"""^\s*-?\s*               # optional list dash
        (?:[A-Za-z0-9_.]+\.)?   # optional dotted prefix (some_module.no_log)
        no_log\s*:\s*           # the key
        (true|True|TRUE|        # forbidden literal truthy values
         yes|Yes|YES|
         on|On|ON)\b
        \s*(?:\#.*)?$           # optional trailing comment
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: {self.snippet}"


def _iter_yaml_files(repo_root: Path) -> Iterable[Path]:
    for sub in SCAN_DIRS:
        base = repo_root / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix in (".yml", ".yaml") and path.is_file():
                yield path


def _scan_file(path: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        text = read_text(str(path))
    except (IOError, OSError, UnicodeDecodeError):
        return findings

    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if _LITERAL_TRUE_RE.match(line):
            findings.append(Finding(file=path, line=idx, snippet=line.strip()))
    return findings


class TestNoLiteralNoLogTrue(unittest.TestCase):
    def test_no_log_must_use_mask_credentials_variable(self) -> None:
        """`no_log: true` (or `yes`/`on`) is forbidden in Ansible YAML.

        Hard-coding `no_log: true` makes it impossible to opt out of credential
        masking when debugging a failing task — operators have to edit the role
        on disk and re-run. Use the project-wide toggle instead:

            no_log: "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"

        `MASK_CREDENTIALS_IN_LOGS` is defined in
        ``group_vars/all/00_general.yml`` and defaults to ``true``, so the
        production behaviour is identical, but operators can flip it for a
        single play with ``-e MASK_CREDENTIALS_IN_LOGS=false`` when they need
        the masked values to surface in logs for diagnosis.
        """
        findings: List[Finding] = []
        for yml in _iter_yaml_files(PROJECT_ROOT):
            findings.extend(_scan_file(yml))

        if findings:
            formatted = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(
                "Found forbidden literal `no_log: true` (or yes/on). "
                "Replace with:\n"
                '    no_log: "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"\n'
                "so the operator can disable masking for diagnosis without "
                "editing the role.\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
