import os
from pathlib import Path

ATTRIBUTES = ("mode", "owner", "group")

ATTRIBUTE_SPEC = {
    "mode": {"type": "raw"},
    "owner": {"type": "str"},
    "group": {"type": "str"},
}


class DirectoryError(Exception):
    pass


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


def ensure_all(module, entries):
    """Ensure every entry in order and fail the module on the first error.

    Args:
        module: the running ``AnsibleModule``.
        entries: list of ``{path, mode, owner, group}``.

    Returns:
        ``(changed_paths, diffs)``: the paths that were created or whose
        attributes changed, and one ``before``/``after`` record per such path.
    """
    changed_paths = []
    diffs = []
    for entry in entries:
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
    return changed_paths, diffs
