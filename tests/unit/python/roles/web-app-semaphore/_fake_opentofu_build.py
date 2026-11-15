from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-semaphore"
OPENTOFU = ROLE_DIR / "files" / "opentofu"
BUILD = ROLE_DIR / "files" / "shell" / "opentofu" / "build.sh"
FLAVORS = ("knot", "route53", "cloudflare")
MIRROR_LINE = re.compile(r'^(\s*path\s*=\s*)"[^"]+"(\s*)$', re.MULTILINE)
FAKE_TOFU = """#!{python}
import json, os, pathlib, re, sys
args = sys.argv[1:]
cwd = pathlib.Path.cwd()
if args and args[0].startswith("-chdir="):
    cwd = pathlib.Path(args.pop(0).split("=", 1)[1])
command = args[0] if args else ""
if command == "version":
    print("OpenTofu v{version}")
    sys.exit(0)
def text(name):
    path = cwd / name
    return path.read_text() if path.is_file() else None
lock = text(".terraform.lock.hcl") or ""
providers = re.findall(r'^provider "([^"]+)"', lock, re.MULTILINE)
record = {{
    "argv": args,
    "main": text("main.tf.json"),
    "cli_config": os.environ.get("TF_CLI_CONFIG_FILE"),
    "dns": text("modules/dns/main.tf.json"),
    "workspace": text("workspace.json"),
    "catalog": text("catalog.json"),
}}
with open(os.environ["FAKE_TOFU_LOG"], "a") as handle:
    handle.write(json.dumps(record) + "\\n")
if command == "providers":
    for provider in providers:
        (pathlib.Path(args[-1]) / provider).mkdir(parents=True, exist_ok=True)
if command == "init":
    config = pathlib.Path(os.environ["TF_CLI_CONFIG_FILE"]).read_text()
    mirror = pathlib.Path(re.search(r'path\\s*=\\s*"([^"]+)"', config).group(1))
    for provider in providers:
        if not (mirror / provider).is_dir():
            print(f"provider {{provider}} is not in the mirror", file=sys.stderr)
            sys.exit(1)
"""
FAKE_APPIMAGE = """#!/bin/sh
[ "$1" = "--appimage-extract" ] || exit 64
mkdir -p squashfs-root/usr/bin
printf '%s' '{script}' > squashfs-root/usr/bin/{name}
chmod 0755 squashfs-root/usr/bin/{name}
"""


class Build:
    """Args:
    version: the version the fake ``tofu version`` reports.
    """

    def __init__(self, version):
        self.directory = Path(tempfile.mkdtemp(prefix="opentofu-build-test-"))
        self.opentofu = self.directory / "opentofu"
        shutil.copytree(OPENTOFU, self.opentofu)
        self.mirror = self.directory / "mirror"
        tofurc = self.opentofu / "tofurc"
        tofurc.write_text(
            MIRROR_LINE.sub(
                rf'\g<1>"{self.mirror}"\g<2>', read_text(str(OPENTOFU / "tofurc"))
            ),
            encoding="utf-8",
        )
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        tofu = self.bin / "tofu"
        tofu.write_text(
            FAKE_TOFU.format(python=sys.executable, version=version), encoding="utf-8"
        )
        tofu.chmod(0o755)
        self.log = self.directory / "tofu.log"
        self.script = BUILD

    def run(self, *arguments):
        """Args:
            arguments: the ``build.sh`` command and its arguments.

        Returns:
            The finished process; :meth:`calls` then holds its calls only.
        """
        self.log.unlink(missing_ok=True)
        return subprocess.run(
            ["bash", str(self.script), *arguments],
            env={
                "PATH": f"{self.bin}:/usr/bin:/bin",
                "HOME": str(self.directory),
                "TMPDIR": str(self.directory),
                "FAKE_TOFU_LOG": str(self.log),
                "TF_CLI_CONFIG_FILE": "/planted/tofurc",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def calls(self):
        if not self.log.is_file():
            return []
        lines = self.log.read_text().splitlines()  # nocheck: cache-read  stub call log
        return [json.loads(line) for line in lines]

    def archive(self, script, member="tofu"):
        """Args:
            script: the text of the binary inside the archive.
            member: the path of that binary inside the archive.

        Returns:
            ``(path, sha256)`` of a release-shaped ``tar.gz``.
        """
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            data = script.encode()
            info = tarfile.TarInfo(member)
            info.size, info.mode = len(data), 0o755
            archive.addfile(info, io.BytesIO(data))
            readme = tarfile.TarInfo("README.md")
            archive.addfile(readme, io.BytesIO(b""))
        path = self.directory / f"{Path(member).name}.tar.gz"
        path.write_bytes(buffer.getvalue())
        return path, hashlib.sha256(buffer.getvalue()).hexdigest()

    def prefix(self):
        """Returns:
        A ``/usr/local`` stand-in whose ``bin`` exists and holds nothing.
        """
        prefix = self.directory / "usr-local"
        (prefix / "bin").mkdir(parents=True, exist_ok=True)
        return prefix

    def appimage(self, name, script):
        """Args:
            name: the binary the AppImage carries in ``usr/bin``.
            script: the text of that binary.

        Returns:
            ``(path, sha256)`` of an AppImage that extracts like a release.
        """
        text = FAKE_APPIMAGE.format(name=name, script=script)
        path = self.directory / f"{name}.AppImage"
        path.write_text(text, encoding="utf-8")
        return path, hashlib.sha256(text.encode()).hexdigest()

    def close(self):
        shutil.rmtree(self.directory, ignore_errors=True)


def roots():
    """Returns:
    ``{main.tf.json text: root name}`` of every root the build validates.
    """
    paths = [*(OPENTOFU / "roots").iterdir(), OPENTOFU / "records"]
    return {read_text(str(path / "main.tf.json")): path.name for path in paths}
