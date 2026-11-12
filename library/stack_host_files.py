from pathlib import Path

import yaml
from ansible.module_utils.basic import AnsibleModule


def render(documents, suffix, indent, width):
    """Serialise each document to YAML under its own file name.

    Args:
        documents: mapping of base name to the document to write.
        suffix: file extension appended to every base name.
        indent: YAML block indentation.
        width: line width before the dumper wraps a scalar.

    Returns:
        Mapping of file name to file content.
    """
    return {
        f"{name}{suffix}": yaml.safe_dump(
            value,
            default_flow_style=False,
            indent=indent,
            width=width,
            allow_unicode=True,
        )
        for name, value in documents.items()
    }


def survey(directory, suffix):
    """Map every file already carrying *suffix* in *directory* to its path.

    Args:
        directory: the target directory, which need not exist.
        suffix: file extension the caller owns.
    """
    if not directory.is_dir():
        return {}
    return {path.name: path for path in directory.glob(f"*{suffix}")}


def plan(present, wanted, prune):
    """Decide which files to write and which to drop.

    Args:
        present: mapping of file name to path, as returned by ``survey``.
        wanted: mapping of file name to content the caller wants on disk.
        prune: whether files the caller no longer wants are removed.

    Returns:
        A ``(written, removed)`` pair of sorted file-name lists.
    """

    def stale(name, content):
        if name not in present:
            return True
        current = present[name].read_text("utf-8")  # nocheck: cache-read  no utils here
        return current != content

    written = sorted(name for name, content in wanted.items() if stale(name, content))
    removed = sorted(name for name in present if name not in wanted) if prune else []
    return written, removed


def apply(directory, present, wanted, written, removed, mode, directory_mode):
    """Write the planned files and drop the planned ones.

    Args:
        directory: the target directory, created when missing.
        present: mapping of file name to path, as returned by ``survey``.
        wanted: mapping of file name to content.
        written: file names to write.
        removed: file names to delete.
        mode: octal string for the written files.
        directory_mode: octal string for the directory.
    """
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(int(directory_mode, 8))
    file_mode = int(mode, 8)
    for name in written:
        target = directory / name
        target.write_text(wanted[name], encoding="utf-8")
        target.chmod(file_mode)
    for name in removed:
        present[name].unlink()


def main():
    module_args = {
        "path": {"type": "str", "required": True},
        "documents": {"type": "dict", "required": True},
        "suffix": {"type": "str", "required": False, "default": ".yaml"},
        "prune": {"type": "bool", "required": False, "default": True},
        "mode": {"type": "str", "required": False, "default": "0644"},
        "directory_mode": {"type": "str", "required": False, "default": "0755"},
        "indent": {"type": "int", "required": False, "default": 4},
        "width": {"type": "int", "required": False, "default": 100000},
    }
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    directory = Path(module.params["path"])
    suffix = module.params["suffix"]
    wanted = render(
        module.params["documents"],
        suffix,
        module.params["indent"],
        module.params["width"],
    )
    present = survey(directory, suffix)
    written, removed = plan(present, wanted, module.params["prune"])

    if not module.check_mode:
        apply(
            directory,
            present,
            wanted,
            written,
            removed,
            module.params["mode"],
            module.params["directory_mode"],
        )

    module.exit_json(changed=bool(written or removed), written=written, removed=removed)


if __name__ == "__main__":
    main()
