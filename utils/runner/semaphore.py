from __future__ import annotations

import hashlib
import hmac

from utils.runner.store import JobError, checked_name


def pool_runner_names(prefix: str, count: int) -> list[str]:
    """Args:
        prefix: ``services.runner.project_prefix`` of ``svc-runner``.
        count: the number of pool runners, ``RUNNER_COUNT``.

    Returns:
        The queue name of every pool runner, ``<prefix>-1`` to ``<prefix>-<count>``,
        which is also the name of its Semaphore runner row.

    Raises:
        JobError: a name is no compose project name.
    """
    return [checked_name(f"{prefix}-{index}") for index in range(1, int(count) + 1)]


def pool_runner_token(secret: str, runner: str) -> str:
    """Args:
        secret: the ``pool_runner_token`` credential of ``web-app-semaphore``.
        runner: a name of :func:`pool_runner_names`.

    Returns:
        The hex HMAC-SHA256 of the name under the secret: the token the
        Semaphore runner of that pool runner signs in with, which the seeded
        runner row carries and its token file holds, so no token is stored twice.

    Raises:
        JobError: the secret or the name is empty.
    """
    if not str(secret).strip() or not str(runner).strip():
        raise JobError("a pool runner token needs the secret and the runner name")
    return hmac.new(
        str(secret).encode(), str(runner).encode(), hashlib.sha256
    ).hexdigest()
