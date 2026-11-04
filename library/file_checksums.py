"""Report the type, mode and SHA-1 of many paths in one module call.

Args:
    paths: absolute paths to inspect; a symlink is reported, never followed.

Returns:
    states: mapping of every requested path to ``{isreg, isdir, mode, checksum}``.
        ``isreg`` is true only for a regular file and ``isdir`` only for a
        directory; both are false for a missing or unreadable path and for
        anything else. ``mode`` is set for a regular file or a directory and
        ``checksum`` only for a regular file; otherwise they are ``None``.
"""

import os
import stat

from ansible.module_utils.basic import AnsibleModule

ARGUMENT_SPEC = {"paths": {"type": "list", "elements": "str", "required": True}}

_UNKNOWN = {"isreg": False, "isdir": False, "mode": None, "checksum": None}


def path_state(module, path):
    try:
        info = os.lstat(path)
        mode = f"{stat.S_IMODE(info.st_mode):04o}"
        if stat.S_ISDIR(info.st_mode):
            return {"isreg": False, "isdir": True, "mode": mode, "checksum": None}
        if not stat.S_ISREG(info.st_mode):
            return dict(_UNKNOWN)
        digest = module.sha1(path)
    except OSError:
        return dict(_UNKNOWN)
    return {"isreg": True, "isdir": False, "mode": mode, "checksum": digest}


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    module.exit_json(
        changed=False,
        states={path: path_state(module, path) for path in module.params["paths"]},
    )


if __name__ == "__main__":
    main()
