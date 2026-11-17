"""Print the user addons directory of the Blender a workstation user launches.

A Flathub launcher is never started. Flatpak runs every app inside bubblewrap,
which needs an unprivileged user namespace, and a host that restricts those
refuses it (AppArmor on the CI runner: "bwrap: Creating new namespace failed:
Permission denied"). The directory follows from the layout Blender documents
instead: flatpak sets XDG_CONFIG_HOME to ~/.var/app/<app-id>/config, Blender
keeps its user files in $XDG_CONFIG_HOME/blender/<X.Y>/, and the blender.org
archive the Flathub build ships keeps its resources in the <X.Y>/ beside its
executable. A distribution Blender runs unsandboxed and names it itself.

Args:
    argv[1]: the Blender command on PATH.

Exit:
    0 with the addons directory on stdout, 1 with the reason on stderr.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FLATPAK_LAUNCHER = re.compile(
    r"(?P<deploy>.+/app/(?P<app>[^/]+)/[^/]+/[^/]+/[^/]+)/export/bin/(?P=app)"
)
VERSION = re.compile(r"\d+\.\d+")
NAMED = re.compile(r"^ADDONS=(.+)$", re.MULTILINE)
PROBE = (
    "import bpy, sys; sys.stdout.write('ADDONS=' + "
    "bpy.utils.user_resource('SCRIPTS', path='addons', create=True) + '\\n')"
)


class UnresolvedError(Exception):
    pass


def flatpak_addons_dir(deploy: Path, app: str, home: Path) -> Path:
    resources = deploy / "files" / "blender"
    versions = sorted(
        entry.name
        for entry in resources.iterdir()
        if entry.is_dir() and VERSION.fullmatch(entry.name)
    )
    if len(versions) != 1:
        raise UnresolvedError(
            f"{resources} holds the version directories {versions}, expected one"
        )
    config = home / ".var" / "app" / app / "config"
    return config / "blender" / versions[0] / "scripts" / "addons"


def native_addons_dir(launcher: str) -> Path:
    proc = subprocess.run(
        [launcher, "--background", "--python-expr", PROBE],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    named = NAMED.search(proc.stdout)
    if proc.returncode != 0 or named is None:
        raise UnresolvedError(
            f"{launcher} exited {proc.returncode} without naming its addons "
            f"directory: {proc.stderr.strip()[-400:]}"
        )
    return Path(named.group(1))


def addons_dir(command: str, home: Path) -> Path:
    launcher = shutil.which(command)
    if launcher is None:
        raise UnresolvedError(f"{command} is not on PATH {os.environ.get('PATH', '')}")
    flatpak = FLATPAK_LAUNCHER.fullmatch(os.path.realpath(launcher))
    if flatpak is None:
        return native_addons_dir(launcher)
    return flatpak_addons_dir(Path(flatpak["deploy"]), flatpak["app"], home)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: user_addons_dir.py <blender-command>", file=sys.stderr)
        return 1
    try:
        print(addons_dir(argv[1], Path.home()))
    except (UnresolvedError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
