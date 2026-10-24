"""CI debug routine: download every failed job's logs and artefacts, cluster
them by failing task, root-cause each cluster, then fix branch-caused failures
through the compose loop and report external ones as issues. One model step
classifies; an ask step holds for the commit approval."""

from __future__ import annotations

from agents.routines.contract import Step, build as _build, mermaid

STEPS = [
    Step("download", "python -m cli.meta.ci.logs.download for every failed job and sibling run", nxt="cluster"),
    Step("cluster", "python -m cli.meta.ci.logs.analyze to cluster the logs by failing task", nxt="classify"),
    Step("classify", "Static analysis to 99% certainty per cluster, branch-caused or external", "model", nxt="external"),
    Step("external", "gh issue comment or create for each external failure, exact error match first", nxt="branch"),
    Step("branch", "Fix each branch-caused failure through the compose loop in alphabetical order", nxt="approve"),
    Step("approve", "Ask the operator to commit each fix per the commit routine", "ask", nxt="push"),
    Step("push", "git push origin the fix branch, file an issue for anything left unresolved", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("debug_ci", STEPS)
