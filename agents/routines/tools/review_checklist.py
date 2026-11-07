"""Review checklist: the deterministic half of the reviewer's verdict. An agent
pull request fails the checklist when it carries no evidence comment, states a
number its evidence does not back, adds a forbidden comment or touches a
protected path; a changed spec without a passing negative control fails the
next check; and a reviewer never reviews a pull request it authored.
"""

from __future__ import annotations

from agents.routines.tools.negative_control import control_result

PROTECTED_PREFIXES = (
    "agents/firewall/",
    "agents/routines/",
    "utils/firewall/",
    ".github/workflows/",
)
PROTECTED_NAMES = ("AGENTS.md", "SOUL.md")


def authored_by(author: str, reviewer: str) -> bool:
    """Return whether ``reviewer`` authored the pull request.

    Args:
        author: the forge account that opened the pull request.
        reviewer: the forge account the reviewer acts as.
    """
    return bool(author.strip()) and author.strip().lower() == reviewer.strip().lower()


def protected_paths_touched(changed_files: list[str]) -> list[str]:
    """Return the changed files that lie under a protected path, in order.

    Args:
        changed_files: the repository-relative paths the pull request changes.
    """
    return [
        path
        for path in changed_files
        if path.startswith(PROTECTED_PREFIXES)
        or path.rsplit("/", 1)[-1] in PROTECTED_NAMES
    ]


def checklist_failures(
    *,
    evidence: str,
    unbacked: list[str],
    offending: list[str],
    changed_files: list[str],
) -> list[str]:
    """Return one reason per failed checklist item; empty means it passes.

    Args:
        evidence: the pull request's evidence comment.
        unbacked: the numbers of the pull request text its evidence lacks.
        offending: the forbidden comments the diff adds.
        changed_files: the repository-relative paths the pull request changes.
    """
    failures: list[str] = []
    if not evidence.strip():
        failures.append("no evidence comment")
    if unbacked:
        failures.append(f"numbers without evidence: {', '.join(unbacked)}")
    if offending:
        failures.append(f"{len(offending)} forbidden comment(s) added")
    touched = protected_paths_touched(changed_files)
    if touched:
        failures.append(f"touches protected paths: {', '.join(touched)}")
    return failures


def specs_without_control(
    changed_specs: list[str], controls: dict[str, tuple[bool, bool]]
) -> list[str]:
    """Return the changed specs whose negative control did not pass.

    Args:
        changed_specs: the specs the pull request adds or changes.
        controls: per spec, whether it turned red with its input broken and
            green again with the input restored.
    """
    return [
        spec
        for spec in changed_specs
        if not control_result(*controls.get(spec, (False, False)))
    ]
