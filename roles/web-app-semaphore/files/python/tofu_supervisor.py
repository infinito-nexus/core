"""Args:
<runner pid>: the process that starts this supervisor as the leader of a new
    process group; once it dies, the supervisor SIGKILLs that group.
<command> [<argument> ...]: what runs in that group, e.g. ``tofu apply``.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys

PR_SET_PDEATHSIG = 1


def _kill_group(_signum, _frame):
    os.killpg(0, signal.SIGKILL)


def _interrupted(_signum, _frame):
    return None


def tie_to_runner(runner):
    """Args:
        runner: the pid of the runner that started this supervisor.

    Returns:
        Whether the runner still lives; from here on the kernel sends this
        supervisor SIGTERM once it dies.

    Raises:
        OSError: ``prctl`` refused the death signal.
    """
    prctl = ctypes.CDLL(None, use_errno=True).prctl
    if prctl(PR_SET_PDEATHSIG, int(signal.SIGTERM)) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return os.getppid() == runner


def main(argv):
    """Args:
        argv: ``[script, runner pid, command, *arguments]``.

    Returns:
        The exit code of the command, ``128 + n`` when signal ``n`` ended it,
        or ``128 + SIGTERM`` when the runner died before the command started.
    """
    signal.signal(signal.SIGTERM, _kill_group)
    signal.signal(signal.SIGINT, _interrupted)
    if not tie_to_runner(int(argv[1])):
        return 128 + signal.SIGTERM
    code = subprocess.call(argv[2:])
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
