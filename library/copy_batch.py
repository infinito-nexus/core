"""Write the differing entries of a directory copy in one module call.

Every path is handled like ``ansible.builtin.copy`` handles one entry of a
recursive copy: a missing parent directory is created and receives
``directory_mode`` while an existing one stays as found, a file is replaced
through ``atomic_move`` and receives ``mode``, and a leaf directory is ensured
like ``ansible.builtin.file`` with ``state: directory``. Files are handled in
the order of ``tree``, which is the order the copy action walks the source
in, and leaf directories after them.
Nothing is written when a file path exists as anything but a regular file, a
leaf directory path as anything but a directory, a missing path lies below
anything but a directory, or two paths of ``tree`` name the same remote
entry; the call then only reports ``refused``.

Args:
    src: tar archive holding exactly one regular member per entry of ``files``.
    dest: absolute destination directory.
    files: list of ``{path, checksum}`` in source walk order, ``path``
        relative to ``dest`` and ``checksum`` the SHA-1 of its archive member.
    settled: relative paths of regular files whose content is in place; only
        ``mode`` is enforced on them.
    directories: relative paths of leaf directories to ensure.
    tree: relative path of every file and leaf directory of the source tree,
        in walk order; holds every path of ``files``, ``settled`` and
        ``directories``.
    mode: mode of every path in ``files`` and ``settled``.
    directory_mode: mode of every directory this call creates and of every
        path in ``directories``; ``None`` keeps the mode the umask gives.
    unsafe_writes: the file common argument of the same name, handed to
        ``atomic_move`` as the copy module does.

Returns:
    changed: whether any file, mode or directory changed.
    refused: the reasons nothing was written; present only then.
"""

import hashlib
import os
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from ansible.module_utils.basic import FILE_COMMON_ARGUMENTS, AnsibleModule

ARGUMENT_SPEC = {
    "src": {"type": "path", "required": True},
    "dest": {"type": "path", "required": True},
    "files": {
        "type": "list",
        "elements": "dict",
        "required": True,
        "options": {
            "path": {"type": "str", "required": True},
            "checksum": {"type": "str", "required": True},
        },
    },
    "settled": {"type": "list", "elements": "str", "required": True},
    "directories": {"type": "list", "elements": "str", "required": True},
    "tree": {"type": "list", "elements": "str", "required": True},
    "mode": {"type": "raw", "required": True},
    "directory_mode": {"type": "raw"},
    "unsafe_writes": FILE_COMMON_ARGUMENTS["unsafe_writes"],
}

_CHUNK = 1 << 20


def is_relative(name):
    """Tell whether *name* is a normalised path strictly below the destination.

    Args:
        name: relative path from the module arguments or the archive.
    """
    path = PurePosixPath(name)
    return (
        bool(path.parts)
        and str(path) == name
        and not path.is_absolute()
        and ".." not in path.parts
    )


def blocker(path, is_kind, kind, may_be_missing):
    """Name what keeps *path* from taking an entry of the wanted type.

    Args:
        path: absolute destination path.
        is_kind: ``stat.S_ISREG`` or ``stat.S_ISDIR``; an existing entry must
            pass it, so a symlink never does.
        kind: the wanted type in words.
        may_be_missing: whether a missing *path* below a directory is fine.

    Returns:
        ``None`` when *path* can take the entry, else the reason it cannot.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not may_be_missing:
            return f"{path} is missing"
        parent = path.parent
        while not os.path.lexists(parent):
            parent = parent.parent
        return None if parent.is_dir() else f"{parent} is not a directory"
    except OSError as error:
        return f"{path}: {error.strerror}"
    return None if is_kind(info.st_mode) else f"{path} is not {kind}"


def aliases(dest, tree):
    """Name the paths of *tree* that reach the same remote entry.

    Args:
        dest: the destination directory.
        tree: relative paths of every file and leaf directory of the source.

    Returns:
        One reason per path that reaches an entry an earlier path reaches.
    """
    seen = {}
    reasons = []
    for name in tree:
        path = dest / name
        try:
            info = path.stat()
            key = (info.st_dev, info.st_ino)
        except OSError:
            key = str(Path(os.path.realpath(path.parent)) / path.name)
        if key in seen:
            reasons.append(f"{dest / seen[key]} and {path} reach the same entry")
        else:
            seen[key] = name
    return reasons


def refusals(dest, files, settled, directories, tree):
    """Collect what keeps any path of the call from taking its entry.

    Args:
        dest: the destination directory.
        files: relative paths of the files to write.
        settled: relative paths of the files to keep.
        directories: relative paths of the leaf directories to ensure.
        tree: relative paths of every file and leaf directory of the source.

    Returns:
        The reasons, empty when every path can take its entry.
    """
    checks = [
        *((name, stat.S_ISREG, "a regular file", True) for name in files),
        *((name, stat.S_ISREG, "a regular file", False) for name in settled),
        *((name, stat.S_ISDIR, "a directory", True) for name in directories),
    ]
    reasons = [
        blocker(dest / name, is_kind, kind, may_be_missing)
        for name, is_kind, kind, may_be_missing in checks
    ]
    return [reason for reason in reasons if reason] + aliases(dest, tree)


def members(module, archive, expected):
    """Map every path of *expected* to its archive member, failing on any other.

    Args:
        module: the running module.
        archive: the open tar archive.
        expected: mapping of relative path to the SHA-1 of its member.

    Returns:
        Mapping of relative path to its tar member.
    """
    found = {}
    for member in archive.getmembers():
        name = member.name
        if not is_relative(name):
            module.fail_json(msg=f"archive member {name!r} leaves the destination")
        if name not in expected or name in found:
            module.fail_json(msg=f"archive member {name!r} is unexpected or repeated")
        if not member.isreg():
            module.fail_json(msg=f"archive member {name!r} is not a regular file")
        found[name] = member
    missing = sorted(set(expected) - set(found))
    if missing:
        module.fail_json(msg=f"archive lacks {', '.join(missing)}")
    return found


def sha1(archive, member):
    """Return the SHA-1 of the content of *member*.

    Args:
        archive: the open tar archive.
        member: a regular tar member.
    """
    digest = hashlib.sha1(usedforsecurity=False)
    with archive.extractfile(member) as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def attributes(module, path, mode, changed):
    """Apply *mode* to *path* like the copy and file modules do.

    Args:
        module: the running module.
        path: the file or directory.
        mode: the wanted mode, or ``None`` to leave it.
        changed: the change state so far.

    Returns:
        The change state including this call.
    """
    file_args = module.load_file_common_arguments({"path": str(path), "mode": mode})
    return module.set_fs_attributes_if_different(file_args, changed)


def make_directories(module, directory, directory_mode):
    """Create *directory* and its missing parents, each with *directory_mode*.

    Args:
        module: the running module.
        directory: the directory that must exist.
        directory_mode: mode of every directory created, or ``None``.

    Returns:
        Whether a directory was missing.
    """
    missing = []
    while not os.path.lexists(directory):
        missing.append(directory)
        directory = directory.parent
    for path in reversed(missing):
        try:
            path.mkdir()
        except FileExistsError:
            if not path.is_dir():
                raise
        attributes(module, path, directory_mode, True)
    return bool(missing)


def write(module, archive, member, target, workdir):
    """Replace *target* atomically with the content of *member*.

    Args:
        module: the running module, whose ``atomic_move`` keeps the owner,
            group and SELinux context of a replaced file.
        archive: the open tar archive.
        member: the tar member holding the new content.
        target: destination path.
        workdir: directory the content is staged in before the move.
    """
    descriptor, staged = tempfile.mkstemp(dir=workdir)
    try:
        with os.fdopen(descriptor, "wb") as out, archive.extractfile(member) as data:
            shutil.copyfileobj(data, out)
        module.atomic_move(
            staged, str(target), unsafe_writes=module.params["unsafe_writes"]
        )
    finally:
        Path(staged).unlink(missing_ok=True)


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC)
    params = module.params
    dest = Path(params["dest"])
    files = [entry["path"] for entry in params["files"]]
    expected = {entry["path"]: entry["checksum"] for entry in params["files"]}
    settled, directories = params["settled"], params["directories"]
    kept = set(settled)
    directory_mode = params["directory_mode"]
    names = [*files, *settled, *directories, *params["tree"]]
    unsafe = sorted({name for name in names if not is_relative(name)})
    if unsafe:
        module.fail_json(msg=f"paths leave {dest}: {', '.join(unsafe)}")
    if len(expected) != len(files):
        module.fail_json(msg="files repeat a path")
    outside = sorted(set(names) - set(params["tree"]))
    if outside:
        module.fail_json(msg=f"paths missing from tree: {', '.join(outside)}")
    refused = refusals(dest, files, settled, directories, params["tree"])
    if refused:
        module.exit_json(changed=False, refused=refused)

    changed = False
    with tarfile.open(params["src"], mode="r:") as archive:
        found = members(module, archive, expected)
        mismatched = [
            name for name in files if sha1(archive, found[name]) != expected[name]
        ]
        if mismatched:
            module.fail_json(
                msg=f"archived files do not match their checksum: {', '.join(mismatched)}"
            )
        for name in params["tree"]:
            target = dest / name
            if name in kept:
                changed = attributes(module, target, params["mode"], changed)
            if name not in expected:
                continue
            try:
                changed = (
                    make_directories(module, target.parent, directory_mode) or changed
                )
                write(module, archive, found[name], target, module.tmpdir)
            except Exception as error:  # noqa: BLE001 - atomic_move raises a bare Exception
                module.fail_json(
                    msg=f"Failed to write {target}: {error}",
                    path=str(target),
                    changed=changed,
                )
            changed = attributes(module, target, params["mode"], True)
    for name in directories:
        path = dest / name
        try:
            created = make_directories(module, path, directory_mode)
        except OSError as error:
            module.fail_json(
                msg=f"Failed to create {path}: {error}",
                path=str(path),
                changed=changed,
            )
        changed = created or attributes(module, path, directory_mode, changed)
    module.exit_json(changed=changed)


if __name__ == "__main__":
    main()
