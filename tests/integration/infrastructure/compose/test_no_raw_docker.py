from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at, is_suppressed_in_head
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class Finding:
    file: str
    line_no: int
    line: str
    rule: str
    suggestion: str


WHITELIST_SUFFIXES: tuple[str, ...] = (
    ".md",
    ".js",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".pdf",
    ".lock",
)

WHITELIST_FILENAMES: tuple[str, ...] = ("LICENSE",)

WHITELIST_PATH_FRAGMENTS: tuple[str, ...] = (
    "/.git/",
    "/.venv/",
    "/.mypy_cache/",
    "/.pytest_cache/",
    "/node_modules/",
    "/dist/",
    "/build/",
    "/.github/",
    "/scripts/",
    "/.tox/",
    "/cli/",
    "infinito_nexus.egg-info/",
)


_CMD_PREFIX = r"""
(?:
    ^\s*                                  # line start
  | [;&(]\s*                               # ; & (
  | \|\s*                                  # pipe
  | &&\s*                                  # &&
  | \|\|\s*                                # ||
  | \$(?:\(|\{)\s*                         # $(  or ${
)
"""

_DOCKER_BIN = r"(?:sudo\s+)?(?:/usr/bin/|/bin/|/usr/local/bin/)?docker"
_DOCKER_COMPOSE_BIN = r"(?:sudo\s+)?(?:/usr/bin/|/bin/|/usr/local/bin/)?docker-compose"

_DOCKER_SUBCOMMANDS = (
    "run",
    "exec",
    "ps",
    "inspect",
    "logs",
    "pull",
    "push",
    "build",
    "login",
    "logout",
    "tag",
    "rm",
    "rmi",
    "start",
    "stop",
    "restart",
    "kill",
    "cp",
    "info",
    "version",
    "events",
    "stats",
    "system",
    "container",
    "image",
    "volume",
    "network",
    "manifest",
    "buildx",
    "builder",
    "context",
)

_COMPOSE_VERBS = (
    "up",
    "down",
    "pull",
    "push",
    "build",
    "config",
    "ps",
    "logs",
    "exec",
    "run",
    "start",
    "stop",
    "restart",
    "rm",
    "create",
    "images",
    "top",
)

RE_DOCKER_CMD = re.compile(
    rf"{_CMD_PREFIX}{_DOCKER_BIN}\s+(?:{'|'.join(map(re.escape, _DOCKER_SUBCOMMANDS))})\b",
    re.IGNORECASE | re.VERBOSE,
)

RE_DOCKER_COMPOSE_CMD = re.compile(
    rf"{_CMD_PREFIX}{_DOCKER_BIN}\s+compose\s+(?:{'|'.join(map(re.escape, _COMPOSE_VERBS))})\b",
    re.IGNORECASE | re.VERBOSE,
)

RE_DOCKER_DASH_COMPOSE_CMD = re.compile(
    rf"{_CMD_PREFIX}{_DOCKER_COMPOSE_BIN}\s+(?:{'|'.join(map(re.escape, _COMPOSE_VERBS))})\b",
    re.IGNORECASE | re.VERBOSE,
)

RULES: tuple[tuple[str, re.Pattern, str], ...] = (
    (
        "docker compose usage",
        RE_DOCKER_COMPOSE_CMD,
        "Use 'compose <verb> ...' instead of 'docker compose <verb> ...'.",
    ),
    (
        "docker-compose usage",
        RE_DOCKER_DASH_COMPOSE_CMD,
        "Use 'compose <verb> ...' instead of 'docker-compose <verb> ...'.",
    ),
    (
        "docker CLI usage",
        RE_DOCKER_CMD,
        "Use 'container <cmd> ...' instead of calling 'docker <cmd> ...' directly.",
    ),
)


def git_ls_files(root: Path) -> list[Path]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"],
            stderr=subprocess.STDOUT,
        )
        rels = [p for p in out.decode("utf-8", errors="replace").split("\0") if p]
        return [root / p for p in rels]
    except Exception:
        results: list[Path] = []
        for path_str in iter_project_files():
            try:
                rel = Path(path_str).relative_to(root).as_posix()
            except ValueError:
                continue
            if any(fragment in f"/{rel}/" for fragment in WHITELIST_PATH_FRAGMENTS):
                continue
            results.append(Path(path_str))
        return results


def is_whitelisted(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()

    if path.name in WHITELIST_FILENAMES:
        return True
    if any(rel.endswith(suf) for suf in WHITELIST_SUFFIXES):
        return True

    rel_wrapped = f"/{rel}/"
    return bool(any(fragment in rel_wrapped for fragment in WHITELIST_PATH_FRAGMENTS))


SUPPRESS_RULE: str = "raw-docker"
HEAD_SCAN_LINES: int = 30


def scan_file(path: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    rel = path.relative_to(root).as_posix()

    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    lines = text.splitlines()
    if is_suppressed_in_head(lines, SUPPRESS_RULE, scan_lines=HEAD_SCAN_LINES):
        return findings

    for idx, line in enumerate(lines, start=1):
        for rule_name, pattern, suggestion in RULES:
            if pattern.search(line):
                if is_suppressed_at(lines, idx, SUPPRESS_RULE, mode="same-or-above"):
                    break
                findings.append(
                    Finding(
                        file=rel,
                        line_no=idx,
                        line=line.rstrip("\n"),
                        rule=rule_name,
                        suggestion=suggestion,
                    )
                )
                break

    return findings


def format_findings(findings: Sequence[Finding]) -> str:
    lines: list[str] = []
    lines.append("Forbidden raw Docker command invocations detected.")
    lines.append("")
    lines.append("Why this matters:")
    lines.append(
        "- We enforce a convenience wrapper ('container' / 'compose') so the container engine can be switched quickly"
    )
    lines.append(
        "  (e.g., Docker -> Podman) without refactoring command strings across the repo."
    )
    lines.append("")
    lines.append("Fix rules:")
    lines.append("- 'docker <cmd> ...'              -> 'container <cmd> ...'")
    lines.append("- 'docker compose <verb> ...'     -> 'compose <verb> ...'")
    lines.append("- 'docker-compose <verb> ...'     -> 'compose <verb> ...'")
    lines.append("")
    lines.append("Findings:")
    for f in findings:
        lines.append(f"- {f.file}:{f.line_no}: {f.line.strip()}")
        lines.append(f"  -> {f.suggestion}")
    return "\n".join(lines)


class TestNoRawDockerCommands(unittest.TestCase):
    def test_no_raw_docker_commands_in_repo(self) -> None:
        root = PROJECT_ROOT
        files = git_ls_files(root)

        findings: list[Finding] = []
        for p in files:
            if not p.is_file():
                continue
            if is_whitelisted(p, root):
                continue
            findings.extend(scan_file(p, root))

        if findings:
            self.fail(format_findings(findings))


if __name__ == "__main__":
    unittest.main()
