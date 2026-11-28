from __future__ import annotations

import grp
import os
import re
from typing import TYPE_CHECKING

from utils.cache import ROLES_DIR
from utils.cache.yaml import load_yaml
from utils.infra_inventory import POOL_ROLE
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_USERS
from utils.runner import jobs, store

if TYPE_CHECKING:
    from pathlib import Path

QUEUE_USER = "runner-queue"
DOCKER_SOCKET = "docker.sock"
ROLE_DIR = ROLES_DIR / POOL_ROLE


def project_prefix() -> str:
    """Returns:
    The compose project prefix svc-runner names the job stack of each pool
    runner with.
    """
    return load_yaml(ROLE_DIR / ROLE_FILE_META_SERVICES)["runner"]["project_prefix"]


def runner_stack(name: str, prefix: str) -> bool:
    """Args:
        name: a compose project name, as a job record or ``docker compose ls`` names it.
        prefix: the prefix :func:`project_prefix` returns.

    Returns:
        Whether it is ``<prefix>-<N>``, the job stack of pool runner N as
        svc-runner numbers its instances from 1, and so no other stack on
        the infra runner's daemon.
    """
    return re.fullmatch(rf"{re.escape(prefix)}-[1-9][0-9]*", name) is not None


def queue_refusal(root: Path) -> list[str]:
    """Args:
        root: the queue directory.

    Returns:
        The refusal lines while the queue's gid names another group on this
        host, while this user cannot write the queue, or while its layout
        lets a job swap a directory under its users, each naming the step
        that fixes it; nothing otherwise.
    """
    owner = load_yaml(ROLE_DIR / ROLE_FILE_META_USERS)[QUEUE_USER]
    group, gid = owner["username"], owner["gid"]
    try:
        present = grp.getgrgid(gid).gr_name
    except KeyError:
        present = group
    if present != group:
        return [
            (
                f"[runner] gid {gid} is the group {present} on this host, not "
                f"{group}, so every member of {present} would share the job queue "
                f"{root}; move {present} to a free gid (sudo groupmod -g <gid> "
                f"{present}) before creating {group}"
            )
        ]
    if root.is_dir() and os.access(root, os.W_OK | os.X_OK):
        return [
            (
                f"[runner] the job queue {root} is unsafe to share: {problem}; "
                "make infra-update with INFINITO_DEPLOY_VIA_POOL=true restores "
                "its layout"
            )
            for problem in store.layout_problems(root)
        ]
    if not root.is_dir():
        return [
            (
                f"[runner] the job queue {root} does not exist; make infra-update "
                "with INFINITO_DEPLOY_VIA_POOL=true creates it with the runner pool"
            )
        ]
    return [
        (
            f"[runner] this user cannot write the job queue {root}, which the group "
            f"{group} (gid {gid}) shares with the pool runners; joining it grants "
            "root on this host, because its members reach the Docker daemon of "
            "the privileged infra runner, so add only who may be root here, once "
            f"with sudo groupadd -g {gid} {group} (unless it exists) and sudo "
            f'usermod -aG {group} "$USER", then log in again'
        )
    ]


def docker_host(root: Path) -> str:
    """Args:
        root: the queue directory.

    Returns:
        The ``DOCKER_HOST`` of the socket svc-runner opens in the queue for the
        infra runner's daemon, the daemon every job stack runs on.
    """
    return f"unix://{root / DOCKER_SOCKET}"


def pool_job(root: Path, job_id: str) -> tuple[jobs.Job | None, list[str]]:
    """Args:
        root: the queue directory.
        job_id: the job an operator names with ``job=<id>``.

    Returns:
        The job with no refusal while it is held or running and its record
        names its runner's own job stack; else None with the refusal lines of
        an unusable queue, an unknown id, another state or a foreign stack.
    """
    refusals = queue_refusal(root)
    if refusals:
        return None, refusals
    try:
        record = jobs.job(root, job_id)
    except jobs.JobError as exc:
        return None, [f"[runner] {exc}"]
    if record.state not in (jobs.HELD, jobs.RUNNING) or record.stack is None:
        return None, [
            (
                f"[runner] job {job_id} is {record.state}, not {jobs.HELD} or "
                f"{jobs.RUNNING}, so it has no stack"
            )
        ]
    if record.stack != record.runner or not runner_stack(
        record.stack, project_prefix()
    ):
        return None, [
            (
                f"[runner] job {job_id} names the stack {record.stack} on runner "
                f"{record.runner}, which is no pool runner's own job stack"
            )
        ]
    return record, []
