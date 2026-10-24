"""Ensure many directories exist in one module call.

Args:
    entries: list of ``{path, mode, owner, group}``, each path with its own
        attributes; mutually exclusive with ``paths``.
    paths: list of paths that all receive ``mode``, ``owner`` and ``group``.
    mode: mode of every path in ``paths``.
    owner: owner of every path in ``paths``.
    group: group of every path in ``paths``.

    Every path is handled like ``ansible.builtin.file`` with
    ``state: directory``: a symlink is followed, a missing path is created
    together with its missing parents, which receive the same attributes, an
    existing directory gets every given attribute that differs, and an
    attribute left out stays as found.

Returns:
    changed_paths: the paths that were created or whose attributes changed.
    diff: one ``before``/``after`` record per changed path, in diff mode.
"""

import os
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule

ATTRIBUTES = ("mode", "owner", "group")

ATTRIBUTE_SPEC = {
    "mode": {"type": "raw"},
    "owner": {"type": "str"},
    "group": {"type": "str"},
}

ARGUMENT_SPEC = {
    "entries": {
        "type": "list",
        "elements": "dict",
        "options": {"path": {"type": "path", "required": True}, **ATTRIBUTE_SPEC},
    },
    "paths": {"type": "list", "elements": "path"},
    **ATTRIBUTE_SPEC,
}

MUTUALLY_EXCLUSIVE = [["entries", name] for name in ("paths", *ATTRIBUTES)]

REQUIRED_ONE_OF = [["entries", "paths"]]


class DirectoryError(Exception):
    pass


def requested_entries(params):
    if params["entries"] is not None:
        return params["entries"]
    return [
        {"path": path, **{name: params[name] for name in ATTRIBUTES}}
        for path in params["paths"]
    ]


def path_state(path):
    target = Path(path)
    if target.is_symlink():
        return "link"
    if target.is_dir():
        return "directory"
    if target.exists():
        return "file"
    return "absent"


def apply_attributes(module, path, entry, changed, diff):
    file_args = module.load_file_common_arguments(
        {"path": path, **{name: entry[name] for name in ATTRIBUTES}}
    )
    return module.set_fs_attributes_if_different(file_args, changed, diff, expand=False)


def create(module, path, entry, diff):
    changed = False
    current = ""
    for part in path.strip("/").split("/"):
        current = f"{current}/{part}"
        candidate = Path(current)
        if candidate.exists():
            continue
        try:
            candidate.mkdir()
            changed = True
        except FileExistsError:
            if not candidate.is_dir():
                raise
        changed = apply_attributes(module, current, entry, changed, diff)
    return changed


def ensure(module, entry):
    path = entry["path"]
    if not Path(path).is_absolute():
        raise DirectoryError(f"{path!r} is not an absolute path")
    if Path(path).is_symlink():
        path = os.path.realpath(path)
    state = path_state(path)
    diff = {"before": {"path": path}, "after": {"path": path}}
    if state == "directory":
        return apply_attributes(module, path, entry, False, diff), diff
    if state != "absent":
        raise DirectoryError(f"{path} already exists as a {state}")
    diff["before"]["state"] = state
    diff["after"]["state"] = "directory"
    if module.check_mode:
        return True, diff
    try:
        return create(module, path, entry, diff), diff
    except OSError as error:
        raise DirectoryError(f"Could not create {path}: {error}") from error


def main():
    module = AnsibleModule(
        argument_spec=ARGUMENT_SPEC,
        mutually_exclusive=MUTUALLY_EXCLUSIVE,
        required_one_of=REQUIRED_ONE_OF,
        supports_check_mode=True,
    )
    changed_paths = []
    diffs = []
    for entry in requested_entries(module.params):
        try:
            changed, diff = ensure(module, entry)
        except DirectoryError as error:
            module.fail_json(
                msg=str(error),
                path=entry["path"],
                changed=bool(changed_paths),
                changed_paths=changed_paths,
            )
        if changed:
            changed_paths.append(entry["path"])
            diffs.append(diff)
    result = {"changed": bool(changed_paths), "changed_paths": changed_paths}
    if module._diff:
        result["diff"] = diffs
    module.exit_json(**result)


if __name__ == "__main__":
    main()
