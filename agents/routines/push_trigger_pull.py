"""Push trigger pull routine: free runners, push the confirmed branch, draft its
pull request, trigger entry-manual-steer.yml and watch it, then ready the pull
request only on a green run."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "free",
        "gh run list --status in_progress, cancel only the runs the operator names",
        "ask",
        nxt="branch",
    ),
    Step(
        "branch",
        "Resolve git rev-parse --abbrev-ref HEAD and freeze the branch the operator confirms",
        "ask",
        nxt="push",
    ),
    Step(
        "push",
        "git push -u origin <branch>, stop and ask on a non-fast-forward reject, never force unasked",
        nxt="draft",
    ),
    Step(
        "draft",
        "gh pr list --head <branch>, create a draft pull request or demote the ready one, freeze its number",
        nxt="trigger",
    ),
    Step(
        "trigger",
        "git fetch origin main, compute scope, gh workflow run entry-manual-steer.yml --ref <branch>",
        nxt="watch",
    ),
    Step(
        "watch",
        "Resolve the new run id against the previous one and gh run watch <run-id> --exit-status",
        nxt="close",
    ),
    Step(
        "close",
        "On success gh pr ready <pr-number>; on failure ask the operator and leave the pull request draft",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("push_trigger_pull", STEPS)
