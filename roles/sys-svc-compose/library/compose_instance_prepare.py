"""Ensure a compose instance's directories and probe its state in one call.

Args:
    directories: paths ensured like ``directory_batch`` ``paths``.
    mode: mode of every path in ``directories``.
    instance: compose project directory ``compose ps`` runs in.
    pending_marker: path reported in ``pending``.
    running_check: whether to run ``compose ps -q --filter status=running``
        in ``instance``.

Returns:
    changed_paths: the directories that were created or whose mode changed.
    diff: one ``before``/``after`` record per changed directory, in diff mode.
    pending: whether ``pending_marker`` exists, a symlink not followed.
    running: ``rc``, ``stdout`` and ``stderr`` of ``compose ps``, each stream
        stripped of trailing newlines; null when ``running_check`` is false or
        in check mode.
"""

import os

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.directory_batch import ensure_all

ARGUMENT_SPEC = {
    "directories": {"type": "list", "elements": "path", "required": True},
    "mode": {"type": "raw", "required": True},
    "instance": {"type": "path", "required": True},
    "pending_marker": {"type": "path", "required": True},
    "running_check": {"type": "bool", "required": True},
}

RUNNING_ARGS = ("ps", "-q", "--filter", "status=running")


def running(module):
    if not module.params["running_check"] or module.check_mode:
        return None
    compose = module.get_bin_path("compose", required=True)
    rc, stdout, stderr = module.run_command(
        [compose, *RUNNING_ARGS], cwd=module.params["instance"]
    )
    return {"rc": rc, "stdout": stdout.rstrip("\r\n"), "stderr": stderr.rstrip("\r\n")}


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    entries = [
        {"path": path, "mode": module.params["mode"], "owner": None, "group": None}
        for path in module.params["directories"]
    ]
    changed_paths, diffs = ensure_all(module, entries)
    result = {
        "changed": bool(changed_paths),
        "changed_paths": changed_paths,
        "pending": os.path.lexists(module.params["pending_marker"]),
        "running": running(module),
    }
    if module._diff:
        result["diff"] = diffs
    module.exit_json(**result)


if __name__ == "__main__":
    main()
