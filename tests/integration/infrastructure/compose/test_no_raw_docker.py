from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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


# Whitelist: ignore these file endings / filenames / path fragments
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

# Optional: allow docker mentions in specific files (keep empty for strict)
WHITELIST_EXACT_PATHS: tuple[str, ...] = (
    # svc-runner e2e harness drives a throwaway dind sandbox daemon directly
    # (the container/compose wrappers are not present inside the runner image).
    "roles/svc-runner/files/test/local.sh",
)

# Only treat "docker ..." as a command when it appears in a command-like context.
# i.e. start of line or after common shell operators / subshell / command substitution.
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

# Optional sudo and optional absolute path to docker binary.
_DOCKER_BIN = r"(?:sudo\s+)?(?:/usr/bin/|/bin/|/usr/local/bin/)?docker"
_DOCKER_COMPOSE_BIN = r"(?:sudo\s+)?(?:/usr/bin/|/bin/|/usr/local/bin/)?docker-compose"

# Allowlist of real docker top-level subcommands that you consider "valid invocations".
# Extend when needed (keep it explicit to avoid false positives).
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

# Allowlist of compose verbs (docker compose <verb> / docker-compose <verb>)
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

# Compile patterns with VERBOSE for readability.
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

# Rules: order matters (prefer specific messages)
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
        # Fallback to the cached project walk so the lint guard does not
        # need to step around a raw os.walk here. The whitelist filter is
        # applied per-file (instead of pruning directories) which is
        # functionally identical because the only things we pruned in the
        # original walk were entire whitelisted subtrees.
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

    if rel in WHITELIST_EXACT_PATHS:
        return True
    if path.name in WHITELIST_FILENAMES:
        return True
    if any(rel.endswith(suf) for suf in WHITELIST_SUFFIXES):
        return True

    rel_wrapped = f"/{rel}/"
    return bool(any(fragment in rel_wrapped for fragment in WHITELIST_PATH_FRAGMENTS))


def scan_file(path: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    rel = path.relative_to(root).as_posix()

    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    for idx, line in enumerate(text.splitlines(), start=1):
        # Only flag when it looks like a command invocation.
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
