"""Guard: forbid raw `docker` / `docker compose` / `docker-compose` CLI
invocations across the repository.

The project ships a `container` / `compose` wrapper around the underlying
engine so that swapping Docker for Podman (or another OCI runtime) does
not require a sweep of every role. This test fails when a file calls the
raw CLI in a place that should go through the wrapper.

Scope
-----
* Every file ``git ls-files`` lists (plus untracked, non-ignored files)
  is scanned for single-line shell invocations (start of line / after a
  shell separator) like `docker exec ...`, `sudo docker run ...`,
  `docker compose up`, `docker-compose up`. Files matching
  ``WHITELIST_SUFFIXES`` / ``WHITELIST_FILENAMES`` /
  ``WHITELIST_PATH_FRAGMENTS`` are skipped, except role sources.
* Role sources (``roles/**`` with a ``SCAN_EXTENSIONS`` suffix) are always
  scanned, and their YAML files additionally for:

  1. Ansible argv-lists split across lines::

         ansible.builtin.command:
           argv:
             - docker
             - exec
             - "{{ FOO_CONTAINER }}"

  2. Inline shell/command scalars like
     `ansible.builtin.shell: "docker exec ..."`.

The ``community.docker.docker_*`` module ban lives in
``tests/lint/ansible/roles/test_no_raw_docker_module.py``.

Suppression
-----------
Use the unified marker grammar (rule key ``raw-docker``) documented at
``docs/contributing/actions/testing/suppression.md``:

* File-level: ``# nocheck: raw-docker`` anywhere in the first 30 lines
  excludes the whole file. Reserve this for places where the wrapper
  is genuinely unavailable (bootstrap scripts that install the wrapper
  itself, scripts that run on a bare host).
* Per-line: ``# nocheck: raw-docker`` on the offending line or the
  line directly above suppresses that single finding.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.annotations.suppress import (
    is_suppressed_at,
    is_suppressed_in_head,
)
from utils.cache import PROJECT_ROOT
from utils.cache.files import iter_non_ignored_files, read_text, repository_files

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
    ".po",
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
    "/playbooks/update/files/",
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

YAML_SUFFIXES: tuple[str, ...] = (".yml", ".yaml")

RE_ARGV_DOCKER_BLOCK = re.compile(
    r"""argv:[ \t]*\r?\n"""
    r"""(?:[ \t]*-[ \t]+[^\r\n]*\r?\n){0,40}?"""
    r"""(?P<offender>[ \t]*-[ \t]+['"]?docker['"]?[ \t]*\r?\n)""",
)

RE_YAML_KEY_DOCKER_INLINE = re.compile(
    rf"""^\s*(?:-\s*)?(?:ansible\.builtin\.)?(?:shell|command|raw|cmd)\s*:"""
    rf"""\s*['"]?(?:sudo\s+)?(?:/usr/bin/|/bin/|/usr/local/bin/)?docker\s+"""
    rf"""(?:{"|".join(map(re.escape, _DOCKER_SUBCOMMANDS))})\b""",
    re.IGNORECASE,
)

SCAN_EXTENSIONS: tuple[str, ...] = (".yml", ".yaml", ".j2", ".sh")

SCAN_PATH_PREFIX: str = "roles/"

SUPPRESS_RULE: str = "raw-docker"
HEAD_SCAN_LINES: int = 30


def git_ls_files(root: Path) -> list[Path]:
    try:
        return [root / p for p in repository_files(untracked=True)]
    except Exception:
        return [Path(path_str) for path_str in iter_non_ignored_files()]


def is_whitelisted(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()

    if path.name in WHITELIST_FILENAMES:
        return True
    if any(rel.endswith(suf) for suf in WHITELIST_SUFFIXES):
        return True

    rel_wrapped = f"/{rel}/"
    return bool(any(fragment in rel_wrapped for fragment in WHITELIST_PATH_FRAGMENTS))


def is_role_source(rel: str) -> bool:
    return rel.startswith(SCAN_PATH_PREFIX) and rel.endswith(SCAN_EXTENSIONS)


def _line_no_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _scan_yaml_argv_and_inline(text: str, rel: str) -> list[Finding]:
    findings: list[Finding] = []

    for match in RE_ARGV_DOCKER_BLOCK.finditer(text):
        offender_line_offset = match.start("offender")
        offender_text = match.group("offender").rstrip("\r\n")
        findings.append(
            Finding(
                file=rel,
                line_no=_line_no_at(text, offender_line_offset),
                line=offender_text,
                rule="docker argv list-item",
                suggestion=(
                    "Use 'container' as the first argv element (or rewrite as "
                    "'container <cmd> ...' shell scalar) so the engine stays "
                    "swappable."
                ),
            )
        )

    for idx, line in enumerate(text.splitlines(), start=1):
        if RE_YAML_KEY_DOCKER_INLINE.search(line):
            findings.append(
                Finding(
                    file=rel,
                    line_no=idx,
                    line=line.rstrip("\n"),
                    rule="docker inline scalar",
                    suggestion=(
                        "Replace the leading 'docker <cmd>' with 'container "
                        "<cmd>' in this shell/command scalar."
                    ),
                )
            )

    return findings


def scan_text(text: str, rel: str) -> list[Finding]:
    """Apply every rule to `text`. `rel` is the project-relative POSIX
    path used for diagnostic messages and role-YAML rule gating."""
    findings: list[Finding] = []
    seen_offenders = set()

    for idx, line in enumerate(text.splitlines(), start=1):
        for rule_name, pattern, suggestion in RULES:
            if pattern.search(line):
                findings.append(
                    Finding(
                        file=rel,
                        line_no=idx,
                        line=line.rstrip("\n"),
                        rule=rule_name,
                        suggestion=suggestion,
                    )
                )
                seen_offenders.add(idx)
                break

    if rel.startswith(SCAN_PATH_PREFIX) and rel.endswith(YAML_SUFFIXES):
        for finding in _scan_yaml_argv_and_inline(text, rel):
            if finding.line_no in seen_offenders:
                continue
            findings.append(finding)
            seen_offenders.add(finding.line_no)

    return findings


def scan_file(path: Path, rel: str) -> list[Finding]:
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    if is_suppressed_in_head(lines, SUPPRESS_RULE, scan_lines=HEAD_SCAN_LINES):
        return []
    return [
        finding
        for finding in scan_text(text, rel)
        if not is_suppressed_at(
            lines, finding.line_no, SUPPRESS_RULE, mode="same-or-above"
        )
    ]


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


def collect_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in git_ls_files(root):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not is_role_source(rel) and is_whitelisted(path, root):
            continue
        findings.extend(scan_file(path, rel))
    return findings


class TestNoRawDockerCommands(unittest.TestCase):
    def test_no_raw_docker_commands_in_repo(self) -> None:
        findings = collect_findings(PROJECT_ROOT)
        if findings:
            self.fail(format_findings(findings))


if __name__ == "__main__":
    unittest.main()
