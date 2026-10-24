"""Runner iteration routine: change the svc-runner role, gate on make test,
deploy to a systemd host, and confirm the registered runner. One model step
reads the systemd status and the test-e2e-cli output; DinD proves the deploy
structurally only."""

from __future__ import annotations

from agents.routines.contract import Step, build as _build, mermaid

STEPS = [
    Step("edit", "Change the svc-runner role tasks, templates, or vars", nxt="test"),
    Step("test", "make test green before any deploy", nxt="deploy"),
    Step("deploy", "Deploy svc-runner to a systemd host via the standard role path", nxt="inspect"),
    Step("inspect", "Read systemctl is-active actions.runner.* and the test-e2e-cli output", "model", nxt="register"),
    Step("register", "Confirm the runner in the GitHub repository runner list", nxt="done"),
    Step("done", "Report the registered runner, or the DinD structural proof", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_runner", STEPS)
