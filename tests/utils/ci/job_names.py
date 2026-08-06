"""Render CI deploy-job display names from their workflow source of truth.

Single point of truth for test fixtures so they cannot drift back to job
names GitHub never emits -- the bug that silently made ``--failed swarm`` a
no-op was masked by fixtures hand-typed as ``🐳 Compose web-app-x``, which no
real job is ever called.
"""

from __future__ import annotations

import re

from tests.utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.roles.display import display_names

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"

_DEPLOY = {
    "docker": ("test-deploy-compose.yml", "compose"),
    "swarm": ("test-deploy-swarm.yml", "swarm"),
    "host": ("test-deploy-host.yml", "host"),
}
ORCHESTRATOR_PREFIX = {
    "docker": "🎶 Orchestrate CI / test-deploy-compose / ",
    "swarm": "🎶 Orchestrate CI / test-deploy-swarm / ",
    "host": "🎶 Orchestrate CI / test-deploy-host / ",
}
_NAME_RE = re.compile(r"name: (.+)$", re.MULTILINE)


def _template(mode: str, job_id: str | None = None) -> str:
    workflow_file, deploy_job = _DEPLOY[mode]
    job_id = job_id or deploy_job
    block = re.search(
        rf"^  {job_id}:\n((?:    .*\n)+)",
        read_text(str(WORKFLOWS / workflow_file)),
        re.MULTILINE,
    )
    assert block, f"job '{job_id}' not found in {workflow_file}"
    name = _NAME_RE.search(block.group(1))
    assert name, f"no name: in job '{job_id}' of {workflow_file}"
    return name.group(1).strip().strip('"').strip("'")


def discover_job_name(mode: str, distros: str, marker: str = "") -> str:
    """The job display name GitHub emits for *mode*'s discover step.

    Args:
        mode: ``'docker'`` (compose), ``'swarm'`` or ``'host'``.
        distros: the distro list the run swept.
        marker: line suffix, e.g. ``' ⭐'`` for the priority line.
    """
    rendered = _template(mode, "discover").replace("${{ inputs.distros }}", distros)
    return rendered.replace("${{ inputs.marker }}", marker)


def deploy_job_name(
    mode: str, app: str, variant: str = "", *, orchestrated: bool = True
) -> str:
    """The job display name GitHub emits for an ``app`` deploy in ``mode``.

    Args:
        mode: ``'docker'`` (compose) or ``'swarm'``.
        app: role id, e.g. ``'web-app-matomo'``.
        variant: shard token GitHub appends, e.g. ``'0,1'`` (``''`` = single).
        orchestrated: include the ci-orchestrator caller prefix (real runs do).
    """
    rendered = _template(mode).replace(
        "${{ matrix.label }}", display_names().encode(app, variant)
    )
    return (ORCHESTRATOR_PREFIX[mode] if orchestrated else "") + rendered
