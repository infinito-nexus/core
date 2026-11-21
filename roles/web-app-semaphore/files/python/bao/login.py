"""Args:
<token file>: where the task's own OpenBao token lands with mode 0600, from
    ``utils.openbao_client.login`` of the core tree under INFINITO_SRC_DIR
    with SEMAPHORE_JWT, BAO_ROLE, BAO_ADDR and BAO_CACERT.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

TASK_LOGIN = ("BAO_ADDR", "BAO_CACERT", "BAO_ROLE", "SEMAPHORE_JWT")


def main(argv, env):
    """Args:
    argv: the command line after the script name.
    env: the task environment.

    Returns:
        The exit code.
    """
    if len(argv) != 1:
        print("bao/login.py: expects the token file", file=sys.stderr)
        return 2
    sys.path.insert(0, env["INFINITO_SRC_DIR"])
    client = importlib.import_module("utils.openbao_client")
    try:
        token = client.login({k: env[k] for k in TASK_LOGIN if env.get(k)}).token
    except client.OpenBaoError as error:
        print(f"bao/login.py: {error}", file=sys.stderr)
        return 1
    path = Path(argv[0])
    path.touch(mode=0o600)
    path.write_text(token, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], os.environ.copy()))
