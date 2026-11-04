"""Write many files on the stack host in one module call.

Args:
    files: list of ``{path, content}``; each path is written atomically when
        its content differs.
    mode: file mode applied to every path.

Returns:
    changed_paths: the paths whose content or attributes changed.
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
}


def write_file(module, path, content, mode):
    target = Path(path)
    current = None
    if target.exists():
        current = target.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read runs on the managed host, where utils.cache does not exist
    changed = current != content
    if module.check_mode and current is None:
        return changed
    if changed and not module.check_mode:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False
        ) as handle:
            handle.write(content)
        module.atomic_move(handle.name, str(target))
    file_args = module.load_file_common_arguments({"path": str(target), "mode": mode})
    return module.set_fs_attributes_if_different(file_args, changed)


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    changed_paths = [
        entry["path"]
        for entry in module.params["files"]
        if write_file(module, entry["path"], entry["content"], module.params["mode"])
    ]
    module.exit_json(changed=bool(changed_paths), changed_paths=changed_paths)


if __name__ == "__main__":
    main()
