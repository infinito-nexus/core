"""Refuse a Jira image that is older than the build its database was written by.

Usage: build_guard.py DATA_BUILD INSTALL_DIR DATABASE IMAGE

Runs inside the pinned Jira image.

Args:
    DATA_BUILD: ``jira.version.patched`` of the database, empty when Jira never set it.
    INSTALL_DIR: Jira installation directory of the image.
    DATABASE: name of the Jira database, quoted in the report.
    IMAGE: reference of the pinned image, quoted in the report.

Exit 0 when the data records no build or one the image can run, exit 3 when
a newer build wrote the data; the report on stdout names both builds.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

DOWNGRADE_EXIT = 3
BUILD_CLASS = "atlassian-jira/WEB-INF/classes/com/atlassian/jira/util/BuildUtils.class"
BUILD_FIELD = "BUILD_NUMBER"
VERSION_FIELD = "VERSION"

_UTF8 = 1
_STRING = 8
_WIDE = (5, 6)
_SIZES = {3: 4, 4: 4, 5: 8, 6: 8, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4, 15: 3}
_SIZES.update({16: 2, 17: 4, 18: 4, 19: 2, 20: 2})


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, size: int) -> bytes:
        chunk = self.data[self.pos : self.pos + size]
        if len(chunk) != size:
            raise ValueError("truncated class file")
        self.pos += size
        return chunk

    def u2(self) -> int:
        return struct.unpack(">H", self.take(2))[0]

    def u4(self) -> int:
        return struct.unpack(">I", self.take(4))[0]


def string_constants(data: bytes) -> dict[str, str]:
    """Return the ``static final String`` constants a Java class file declares.

    Args:
        data: content of a ``.class`` file.
    """
    reader = _Reader(data)
    if reader.u4() != 0xCAFEBABE:
        raise ValueError("not a Java class file")
    reader.take(4)
    pool: dict[int, tuple[int, object]] = {}
    index, count = 1, reader.u2()
    while index < count:
        tag = reader.take(1)[0]
        if tag == _UTF8:
            pool[index] = (tag, reader.take(reader.u2()).decode("utf-8", "replace"))
        elif tag == _STRING:
            pool[index] = (tag, reader.u2())
        elif tag in _SIZES:
            pool[index] = (tag, reader.take(_SIZES[tag]))
        else:
            raise ValueError(f"unknown constant pool tag {tag}")
        index += 2 if tag in _WIDE else 1
    reader.take(6)
    reader.take(2 * reader.u2())
    constants = {}
    for _ in range(reader.u2()):
        reader.take(2)
        name = pool[reader.u2()][1]
        reader.take(2)
        for _ in range(reader.u2()):
            attribute = pool[reader.u2()][1]
            body = _Reader(reader.take(reader.u4()))
            if attribute == "ConstantValue":
                tag, value = pool[body.u2()]
                if tag == _STRING:
                    constants[name] = pool[value][1]
    return constants


def image_build(install_dir: Path) -> tuple[int, str]:
    """Return the build number and version of the Jira in the image.

    Args:
        install_dir: Jira installation directory.
    """
    constants = string_constants((install_dir / BUILD_CLASS).read_bytes())
    return int(constants[BUILD_FIELD]), constants[VERSION_FIELD]


def downgrade_report(
    *, database: str, image: str, version: str, data: int, pinned: int
) -> str:
    """Return the message that stops the deploy.

    Args:
        database: name of the Jira database.
        image: reference of the pinned image.
        version: Jira version of the pinned image.
        data: build number recorded in the database.
        pinned: build number of the pinned image.
    """
    return (
        f"web-app-jira: the data in database {database} was written by Jira build "
        f"{data}, but the pinned image {image} is Jira {version} build {pinned}. "
        f"Jira refuses to downgrade its data. Set "
        f"applications.web-app-jira.services.jira.version to the release of build "
        f"{data} or newer, or restore the database and the jira_data volume from a "
        f"backup taken before that release."
    )


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "usage: build_guard.py DATA_BUILD INSTALL_DIR DATABASE IMAGE",
            file=sys.stderr,
        )
        return 2
    data_build, install_dir, database, image = argv
    recorded = int(data_build) if data_build.strip() else 0
    pinned, version = image_build(Path(install_dir))
    if recorded > pinned:
        print(
            downgrade_report(
                database=database,
                image=image,
                version=version,
                data=recorded,
                pinned=pinned,
            )
        )
        return DOWNGRADE_EXIT
    print(f"CURRENT: {database} build {recorded or '-'} <= {image} build {pinned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
