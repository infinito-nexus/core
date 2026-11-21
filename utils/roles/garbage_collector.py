from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_in_head, marker_reason
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_garbage_collector

if TYPE_CHECKING:
    from pathlib import Path

GARBAGE_COLLECTOR_TYPES: tuple[str, ...] = ("script", "native")
GARBAGE_COLLECTOR_SCRIPT: str = "files/shell/garbage_collector.sh"
GARBAGE_COLLECTOR_INSTALLER: str = "roles/sys-ctl-cln-apps/tasks/utils/install.yml"
GARBAGE_COLLECTOR_MODES: tuple[str, ...] = ("routine", "pressure")
GARBAGE_COLLECTOR_EXEMPTION: str = "garbage-collector-required"

_REQUIRED_TEXT = {"native": "setting"}
_MODE_BRANCH = {
    "routine": re.compile(r"(?m)^\s*routine(\s*\|\s*pressure)?\s*\)"),
    "pressure": re.compile(r"(?m)^\s*(routine\s*\|\s*)?pressure\s*\)"),
}
_DEFAULT_BRANCH = re.compile(r"(?m)^\s*\*\s*\)")
_NONZERO_EXIT = re.compile(r"\bexit\s+[1-9][0-9]*\b")
_CONTAINER_EXEC = re.compile(r"\bcontainer\s+exec\b")
_EXEC_TIMEOUT = re.compile(r'\stimeout\s+"?\$\{?GARBAGE_COLLECTOR_APP_TIMEOUT\b')
UNBOUNDED_EXEC = 'garbage_collector.sh runs a container exec without timeout "${GARBAGE_COLLECTOR_APP_TIMEOUT}" inside the container'


def _runs_unbounded_exec(text: str) -> bool:
    for line in text.replace("\\\n", " ").splitlines():
        if line.lstrip().startswith("#"):
            continue
        command = _CONTAINER_EXEC.search(line)
        if command and not _EXEC_TIMEOUT.search(line, command.end()):
            return True
    return False


def script_contract_findings(script: Path) -> list[str]:
    """Static findings against the garbage_collector.sh contract.

    Args:
        script: path of a ``garbage_collector.sh``.

    Returns:
        One message per broken rule: a shebang, the executable bit, a branch
        per mode in :data:`GARBAGE_COLLECTOR_MODES`, a ``*)`` branch that exits non-zero, and
        an in-container ``timeout "${GARBAGE_COLLECTOR_APP_TIMEOUT}"`` on every
        ``container exec``.
    """
    text = read_text(str(script))
    findings: list[str] = []
    if not text.startswith("#!"):
        findings.append("garbage_collector.sh has no shebang")
    if not os.access(script, os.X_OK):
        findings.append("garbage_collector.sh is not executable")
    for mode, branch in _MODE_BRANCH.items():
        if not branch.search(text):
            findings.append(
                f"garbage_collector.sh has no case branch for mode '{mode}'"
            )
    default = _DEFAULT_BRANCH.search(text)
    if default is None:
        findings.append(
            "garbage_collector.sh has no '*)' branch rejecting unknown modes"
        )
    else:
        body = text[default.end() :].split(";;", 1)[0]
        if not _NONZERO_EXIT.search(body):
            findings.append("garbage_collector.sh's '*)' branch does not exit non-zero")
    if _runs_unbounded_exec(text):
        findings.append(UNBOUNDED_EXEC)
    return findings


def _registers_installer(role_dir: Path) -> bool:
    tasks = role_dir / "tasks"
    if not tasks.is_dir():
        return False
    return any(
        GARBAGE_COLLECTOR_INSTALLER in read_text(str(path))
        for path in sorted(tasks.rglob("*.yml"))
    )


def _exemption_reason(role_dir: Path) -> str | None:
    """Return the reason of the role's ``nocheck: garbage-collector-required`` head marker.

    Args:
        role_dir: the role directory.

    Returns:
        The stated reason, empty when the marker names none, or None when the
        head of ``meta/services.yml`` carries no marker.
    """
    services = role_dir / ROLE_FILE_META_SERVICES
    if not services.is_file():
        return None
    lines = read_text(str(services)).splitlines()
    if not is_suppressed_in_head(lines, GARBAGE_COLLECTOR_EXEMPTION):
        return None
    return next(
        reason
        for line in lines
        if (reason := marker_reason(line, GARBAGE_COLLECTOR_EXEMPTION)) is not None
    )


def garbage_collector_findings(role_dir: Path, *, required: bool) -> list[str]:
    """Return every problem with the garbage_collector declaration of one role.

    Args:
        role_dir: the role directory.
        required: whether a missing declaration is a finding (invokable roles).

    Returns:
        Human-readable findings; empty when the role is consistent.
    """
    declaration = get_role_garbage_collector(role_dir, role_name=role_dir.name)
    script = role_dir / GARBAGE_COLLECTOR_SCRIPT
    exemption = _exemption_reason(role_dir)
    if declaration is None:
        if script.is_file():
            return [
                f"ships {GARBAGE_COLLECTOR_SCRIPT} but declares no garbage_collector"
            ]
        if exemption is not None:
            return (
                []
                if exemption
                else [f"nocheck: {GARBAGE_COLLECTOR_EXEMPTION} names no reason"]
            )
        return ["declares no garbage_collector"] if required else []
    if exemption is not None:
        return [
            f"declares garbage_collector and carries nocheck: {GARBAGE_COLLECTOR_EXEMPTION}"
        ]
    if not isinstance(declaration, dict):
        return [
            f"garbage_collector must be a mapping, got {type(declaration).__name__}"
        ]
    kind = declaration.get("type")
    if kind not in GARBAGE_COLLECTOR_TYPES:
        return [
            f"garbage_collector.type must be one of {', '.join(GARBAGE_COLLECTOR_TYPES)}, got {kind!r}"
        ]
    findings: list[str] = []
    text_key = _REQUIRED_TEXT.get(kind)
    if text_key is not None:
        value = declaration.get(text_key)
        if not isinstance(value, str) or not value.strip():
            findings.append(
                f"garbage_collector.type {kind} needs a non-empty garbage_collector.{text_key}"
            )
    if kind != "script":
        if script.is_file():
            findings.append(
                f"ships {GARBAGE_COLLECTOR_SCRIPT} but declares garbage_collector.type {kind}"
            )
        return findings
    if not script.is_file():
        return [
            *findings,
            f"declares garbage_collector.type script but ships no {GARBAGE_COLLECTOR_SCRIPT}",
        ]
    findings.extend(script_contract_findings(script))
    if not _registers_installer(role_dir):
        findings.append(
            f"declares garbage_collector.type script but no task includes {GARBAGE_COLLECTOR_INSTALLER}"
        )
    return findings
