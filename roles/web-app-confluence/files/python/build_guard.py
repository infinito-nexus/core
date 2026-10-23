"""Refuse a Confluence image that is older than the build its home was written by.

Usage: build_guard.py HOME INSTALL_DIR VOLUME IMAGE

Runs inside the pinned Confluence image with the home volume mounted.

Args:
    HOME: Confluence home directory, the mount point of the home volume.
    INSTALL_DIR: Confluence installation directory of the image.
    VOLUME: name of the home volume, quoted in the report.
    IMAGE: reference of the pinned image, quoted in the report.

Exit 0 when the home records no build or one the image can run, exit 3 when
a newer build wrote the home; the report on stdout names both builds.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

DOWNGRADE_EXIT = 3
HOME_CONFIG = "confluence.cfg.xml"
BUILD_NUMBER = re.compile(r"<buildNumber>\s*(\d*)\s*</buildNumber>")
JAR_GLOB = "confluence/WEB-INF/lib/com.atlassian.confluence.confluence-[0-9]*.jar"
BUILD_PROPERTIES = "com/atlassian/confluence/default.properties"


def home_build(home: Path) -> int:
    """Return the build number recorded in the home, 0 when none is recorded.

    Args:
        home: Confluence home directory.
    """
    config = home / HOME_CONFIG
    if not config.is_file():
        return 0
    match = BUILD_NUMBER.search(config.read_text(encoding="utf-8"))
    return int(match.group(1)) if match and match.group(1) else 0


def parse_properties(text: str) -> dict[str, str]:
    """Return the key/value pairs of a Java properties text.

    Args:
        text: content of a ``.properties`` file.
    """
    pairs = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] in "#!" or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        pairs[key.strip()] = value.strip()
    return pairs


def image_build(install_dir: Path) -> tuple[int, str]:
    """Return the build number and version of the Confluence in the image.

    Args:
        install_dir: Confluence installation directory.
    """
    jars = sorted(install_dir.glob(JAR_GLOB))
    if len(jars) != 1:
        raise SystemExit(
            f"build_guard.py: expected one {JAR_GLOB} below {install_dir}, found {len(jars)}"
        )
    with zipfile.ZipFile(jars[0]) as jar:
        properties = parse_properties(jar.read(BUILD_PROPERTIES).decode("utf-8"))
    return int(properties["build.number"]), properties["version.number"]


def downgrade_report(
    *, volume: str, image: str, version: str, home: int, pinned: int
) -> str:
    """Return the message that stops the deploy.

    Args:
        volume: name of the home volume.
        image: reference of the pinned image.
        version: Confluence version of the pinned image.
        home: build number recorded in the home.
        pinned: build number of the pinned image.
    """
    return (
        f"web-app-confluence: the home in volume {volume} was written by Confluence "
        f"build {home}, but the pinned image {image} is Confluence {version} build "
        f"{pinned}. Confluence refuses to start on a home of a newer build. Set "
        f"applications.web-app-confluence.services.confluence.version to the release "
        f"of build {home} or newer, or restore {volume} and the database from a backup "
        f"taken before that release."
    )


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: build_guard.py HOME INSTALL_DIR VOLUME IMAGE", file=sys.stderr)
        return 2
    home_dir, install_dir, volume, image = argv
    recorded = home_build(Path(home_dir))
    pinned, version = image_build(Path(install_dir))
    if recorded > pinned:
        print(
            downgrade_report(
                volume=volume,
                image=image,
                version=version,
                home=recorded,
                pinned=pinned,
            )
        )
        return DOWNGRADE_EXIT
    print(f"CURRENT: {volume} build {recorded or '-'} <= {image} build {pinned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
