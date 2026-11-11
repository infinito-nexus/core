"""Write many files on the stack host in one module call.

Args:
    files: list of ``{path, content}``; each path is written atomically when
        its content differs.
    mode: file mode applied to every path.
    diff_paths: the paths of ``files`` whose content change is reported in
        diff mode; the content of every other path stays out of the output.

Returns:
    changed_paths: the paths whose content or attributes changed.
    diff: in diff mode, one before/after entry per ``diff_paths`` path whose
        content differs.
"""

import tempfile
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule

ARGUMENT_SPEC = {
    "files": {
        "type": "list",
        "elements": "dict",
        "required": True,
        "options": {
            "path": {"type": "path", "required": True},
            "content": {"type": "str", "required": True},
        },
    },
    "mode": {"type": "raw", "required": True},
    "diff_paths": {"type": "list", "elements": "path", "required": True},
}


def read_current(target):
    if not target.exists():
        return None
    return target.read_bytes()  # nocheck: cache-read managed host has no utils.cache


def content_diff(path, content):
    current = read_current(Path(path))
    if current == content.encode("utf-8"):
        return None
    return {
        "before_header": path,
        "after_header": path,
        "before": (current or b"").decode("utf-8", errors="replace"),
        "after": content,
    }


def write_file(module, path, content, mode):
    target = Path(path)
    current = read_current(target)
    encoded = content.encode("utf-8")
    changed = current != encoded
    if module.check_mode and current is None:
        return changed
    if changed and not module.check_mode:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            handle.write(encoded)
        module.atomic_move(handle.name, str(target))
    file_args = module.load_file_common_arguments({"path": str(target), "mode": mode})
    return module.set_fs_attributes_if_different(file_args, changed)


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    diff_paths = set(module.params["diff_paths"]) if module._diff else set()
    changed_paths = []
    diffs = []
    for entry in module.params["files"]:
        diff = (
            content_diff(entry["path"], entry["content"])
            if entry["path"] in diff_paths
            else None
        )
        if write_file(module, entry["path"], entry["content"], module.params["mode"]):
            changed_paths.append(entry["path"])
        if diff is not None:
            diffs.append(diff)
    module.exit_json(
        changed=bool(changed_paths), changed_paths=changed_paths, diff=diffs
    )


if __name__ == "__main__":
    main()
