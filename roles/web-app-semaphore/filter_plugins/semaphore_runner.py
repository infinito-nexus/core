from __future__ import annotations

import hashlib
import json
from typing import Any

from ansible.errors import AnsibleFilterError


def semaphore_runner_digest(inputs: dict[str, Any]) -> str:
    """Return the sha256 the runner image is labelled with.

    Args:
        inputs: every build argument of the runner except its base image; the
            values are compared as text, so ``1001`` and ``"1001"`` agree.
    """
    text = {str(name): str(value) for name, value in inputs.items()}
    return hashlib.sha256(
        json.dumps(text, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def semaphore_runner_base(
    inputs_digest: str,
    deploy_base: str,
    deployed_base: str,
    deployed_inputs: str,
    own_round: bool,
) -> str:
    """Pick the base image the Semaphore runner of this deploy is built on.

    Args:
        inputs_digest: ``semaphore_runner_digest`` of the runner in this checkout.
        deploy_base: the Infinito.Nexus image of this deploy.
        deployed_base: base image of the runner the stack host deployed, '' when
            it deployed none or no longer holds that runner or base image.
        deployed_inputs: the inputs label of the deployed runner image, '' when
            it carries none.
        own_round: whether ``web-app-semaphore`` is one of the apps the deploy
            was asked for, as opposed to a provider pulled in by another app.

    Returns:
        ``deployed_base`` when the deploy runs Semaphore only as a provider and
        the deployed runner image carries ``inputs_digest``, so the runner is
        kept; ``deploy_base`` otherwise, so the runner is rebuilt on it.

    Raises:
        AnsibleFilterError: ``inputs_digest`` or ``deploy_base`` is empty.
    """
    if not str(inputs_digest).strip() or not str(deploy_base).strip():
        raise AnsibleFilterError(
            "semaphore_runner_base: the inputs digest and the deploy base image "
            f"must be set, got {inputs_digest!r} and {deploy_base!r}"
        )
    if own_round or not str(deployed_base).strip():
        return deploy_base
    if str(deployed_inputs).strip() != str(inputs_digest):
        return deploy_base
    return str(deployed_base)


def semaphore_runner_findings(lines: list[str], wanted: list[dict]) -> list[str]:
    """Args:
    lines: the stdout lines of ``sql/project/runners.sql.j2``; each ``RUNNER``
        line carries one runner row as JSON with ``name``, ``project`` (the
        project name, null without a project) and ``tags``.
    wanted: ``SEMAPHORE_PLATFORM_RUNNERS_ACTIVE`` (``name``, ``project``,
        ``tag``).

    Returns:
        Every runner row without a project and every platform project that
        does not run on exactly its own runner with exactly its tag.
    """
    rows = [
        json.loads(line[len("RUNNER ") :])
        for line in lines
        if line.startswith("RUNNER ")
    ]
    findings = [
        f"runner {row['name']} has no project" for row in rows if row["project"] is None
    ]
    for runner in wanted:
        held = [row for row in rows if row["project"] == runner["project"]]
        names = sorted(row["name"] for row in held)
        if names != [runner["name"]]:
            findings.append(
                f"project {runner['project']} runs on {names}, expected only {runner['name']}"
            )
        elif held[0]["tags"] != [runner["tag"]]:
            findings.append(
                f"runner {runner['name']} carries {held[0]['tags']}, expected [{runner['tag']!r}]"
            )
    return findings


class FilterModule:
    def filters(self):
        return {
            "semaphore_runner_base": semaphore_runner_base,
            "semaphore_runner_digest": semaphore_runner_digest,
            "semaphore_runner_findings": semaphore_runner_findings,
        }
