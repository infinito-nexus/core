"""Args:
FILE: the federation digest file of the stack host.
SEGMENT: the ``host_segment`` of the host.
LINE: optional, its ``digest_entry`` line, which starts with ``SEGMENT``;
    without it the host's line goes, and the file with its last line.

Returns:
    ``changed`` or ``unchanged`` on stdout.
"""

from __future__ import annotations

import fcntl
import os
import sys
import tempfile
from pathlib import Path

# Exception: release/host.py DIGEST_LOCK takes the same lock, so both values must match.
LOCK_SUFFIX = ".lock"
MODE = 0o644


def converge(path, segment, line):
    """Args:
    path: the digest file, whose directory exists.
    segment: the ``host_segment`` of the host.
    line: its digest line, None to drop it.

    Returns:
        Whether the file changed.

    Raises:
        ValueError: ``line`` does not start with ``segment``, or the file is
            a symbolic link.
    """
    if line is not None and line.split(" ", 1)[0] != segment:
        raise ValueError(f"the line names another host than {segment}")
    handle = os.open(
        f"{path}{LOCK_SUFFIX}", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if path.is_symlink():
            raise ValueError(f"{path} is a symbolic link")
        old = path.read_text(encoding="utf-8") if path.exists() else None
        kept = [
            each
            for each in (old or "").splitlines()
            if each.split(" ", 1)[0] != segment
        ]
        lines = kept + ([line] if line is not None else [])
        text = "".join(f"{each}\n" for each in lines)
        if not lines:
            path.unlink(missing_ok=True)
            return old is not None
        if text == old:
            return False
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".digest-")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            os.fchmod(stream.fileno(), MODE)
        Path(name).replace(path)
        return True
    finally:
        os.close(handle)


def main(argv):
    """Args:
    argv: ``FILE SEGMENT [LINE]``.

    Returns:
        0 once the file holds the host's line or none, 2 on a wrong
        command line.
    """
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    changed = converge(Path(argv[0]), argv[1], argv[2] if len(argv) == 3 else None)
    print("changed" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
