"""Args:
<inventory>: the inventory the play reads; every OpenBao reference of it,
    its group_vars and its host_vars is read once before the play, through
    ``prepare`` of ``cli.administration.deploy.dedicated.openbao`` of the core
    tree under INFINITO_SRC_DIR, with the task token login of SEMAPHORE_JWT,
    BAO_ROLE, BAO_ADDR and BAO_CACERT.
<command> [<argument> ...]: the play, run in place of this process with the
    token of that login in BAO_TOKEN and never before a pre-flight passed.
"""

from __future__ import annotations

import importlib
import os
import sys


def main(argv, env, run=os.execvpe):
    """Args:
    argv: the command line after the script name.
    env: the task environment; it receives BAO_TOKEN of the login.
    run: replaces this process with the play.

    Returns:
        The exit code of a refusal; the play replaces the process otherwise.
    """
    if len(argv) < 2:
        print("bao/preflight.py: expects the inventory and the play", file=sys.stderr)
        return 2
    sys.path.insert(0, env["INFINITO_SRC_DIR"])
    preflight = importlib.import_module("cli.administration.deploy.dedicated.openbao")
    try:
        preflight.prepare(argv[0], env)
    except preflight.OpenBaoPreflightError as error:
        print(f"bao/preflight.py: {error}", file=sys.stderr)
        return 1
    run(argv[1], argv[1:], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], os.environ.copy()))
