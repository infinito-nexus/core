from __future__ import annotations

from cli.administration.deploy.development.stack import runner_compose_argv

TEARDOWN_FLAGS = ("--volumes", "--remove-orphans")


def teardown(stack: str) -> list[str]:
    """Args:
        stack: the compose project of a pool runner's job stack.

    Returns:
        The call that removes that stack with its volumes on the daemon the
        pool runners share, by project name alone.
    """
    return [*runner_compose_argv(stack, "down"), *TEARDOWN_FLAGS]
