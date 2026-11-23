"""
Args:
    The command line of the role's ``files/test/workspace/drill.py``; the
    tests copy this file beside a copy of ``pass.sh`` as its ``drill.py``.

Env:
    FAKE_DRILL_LOG: the file each call is appended to as one JSON list; a
        ``repository`` or ``order`` call ends with the ``<owner>/<name>`` of
        the repository it reaches.
    FAKE_DRILL_REAL: the role's ``drill.py``, whose ``workspace_repository``
        resolves that repository from the apply result.
    FAKE_DRILL_FAIL: a JSON list; a call that starts with it exits 1.
    FAKE_DRILL_OWNER, FAKE_DRILL_BRANCH: the Gitea owner and the branch of
        the workspace repositories, as Semaphore's vars name them.
    FAKE_DRILL_TEMPLATES: a JSON list of the order templates an apply result
        holds, without the workspace.
"""

from __future__ import annotations

import json
import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def real_drill() -> object:
    """Returns:
    The role's ``drill.py``, loaded as a module.
    """
    spec = spec_from_file_location("drill", os.environ["FAKE_DRILL_REAL"])
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply(workspace: str, result: str) -> None:
    """Args:
    workspace: the workspace id.
    result: where the apply result goes, shaped as ``workspace.py`` prints it.
    """
    alias = f"ws-{workspace}"
    entry = {
        "git_url": f"ssh://git@gitea.example:2201/{os.environ['FAKE_DRILL_OWNER']}/{alias}.git",
        "git_branch": os.environ["FAKE_DRILL_BRANCH"],
    }
    templates = json.loads(os.environ["FAKE_DRILL_TEMPLATES"])
    written = {
        "alias": alias,
        "read_key": "read key",
        "templates": {f"{name} {alias}": entry for name in templates},
        "workspace": workspace,
    }
    Path(result).write_text(json.dumps(written), encoding="utf-8")


def main(args: list[str]) -> int:
    """Args:
        args: the drill command line.

    Returns:
        The exit code.
    """
    if args[:2] == ["workspace", "apply"]:
        apply(args[2], args[3])
    elif args[:1] == ["repository"]:
        args = [*args, real_drill().workspace_repository(args[2], args[3])[0]]
    elif args[:1] == ["order"]:
        args = [*args, real_drill().workspace_repository(args[1], args[2])[0]]
    elif args[:1] == ["state"]:
        print("{}")
    with Path(os.environ["FAKE_DRILL_LOG"]).open("a", encoding="utf-8") as log:
        log.write(json.dumps(args) + "\n")
    failing = json.loads(os.environ["FAKE_DRILL_FAIL"])
    return 1 if failing and args[: len(failing)] == failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
