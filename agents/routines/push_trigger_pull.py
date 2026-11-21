"""Push trigger pull routine: free runners, predict the CI matrix for the pull
request text, push the confirmed branch, draft its pull request, trigger
entry-manual-steer.yml and watch it, then ready the pull request only on a
green run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.affected import matrix_line
from agents.routines.tools.branch_prefix import prefix_ok
from agents.routines.tools.fetch import fetch_argv

if TYPE_CHECKING:
    from collections.abc import MutableMapping

_ALLOWED = "✅ allowed"
_REFUSED = "❌ refused"


def _prefix(state: MutableMapping) -> MutableMapping:
    state["prefix"] = _ALLOWED if prefix_ok(state.get("branch", "")) else _REFUSED
    return state


def _predict(state: MutableMapping) -> MutableMapping:
    state["matrix_line"] = matrix_line(state.get("resolver_output", ""))
    return state


def _fetch(state: MutableMapping) -> MutableMapping:
    state["fetch"] = " ".join(fetch_argv("origin", "main"))
    return state


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
        nxt="prefix",
    ),
    Step(
        "prefix",
        "Branch prefix allowed by docs/contributing/artefact/git/branch.md?",
        "decision",
        branches=((_ALLOWED, "predict"), (_REFUSED, "refuse")),
        fn=_prefix,
    ),
    Step(
        "refuse",
        "Stop before the upload and ask the operator for a branch with an allowed prefix",
        "terminal",
    ),
    Step(
        "predict",
        "Run scripts/meta/resolve/diff/affected_roles.sh and keep its predicted matrix size for the pull request text",
        nxt="push",
        fn=_predict,
    ),
    Step(
        "push",
        "git push -u origin <branch>, stop and ask on a non-fast-forward reject, never force unasked",
        nxt="draft",
    ),
    Step(
        "draft",
        "gh pr list --head <branch>, create a draft pull request with the body from python -m cli.contributing.pull_request render and the predicted matrix size line in its text, or demote the ready one, freeze its number",
        nxt="trigger",
    ),
    Step(
        "trigger",
        "Run the fetch command the node writes (git fetch --no-tags origin main), compute scope, gh workflow run entry-manual-steer.yml --ref <branch>",
        nxt="watch",
        fn=_fetch,
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
