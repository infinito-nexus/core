from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.runner.semaphore import pool_runner_token
from utils.runner.store import JobError


def pool_runner_token_filter(secret: str, runner: str) -> str:
    """Args:
        secret: the ``pool_runner_token`` credential of ``web-app-semaphore``.
        runner: the queue name of a pool runner.

    Returns:
        The token of that pool runner's Semaphore runner.

    Raises:
        AnsibleFilterError: the secret or the name is empty.
    """
    try:
        return pool_runner_token(secret, runner)
    except JobError as exc:
        raise AnsibleFilterError(f"pool_runner_token: {exc}") from exc


class FilterModule:
    def filters(self):
        return {"pool_runner_token": pool_runner_token_filter}
